# -*- coding: utf-8 -*-

# Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in
# compliance with the License. A copy of the License is located at
#
#    http://aws.amazon.com/asl/
#
# or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.

"""Alexa Smart Home Lambda Function Sample Code.

This file demonstrates some key concepts when migrating an existing Smart Home skill Lambda to
v3, including recommendations on how to transfer endpoint/appliance objects, how v2 and vNext
handlers can be used together, and how to validate your v3 responses using the new Validation
Schema.

Note that this example does not deal with user authentication, only uses virtual devices, omits
a lot of implementation and error handling to keep the code simple and focused.
"""

import logging
import time
import json
import uuid
from urllib.parse import urlparse
from datetime import datetime

# Imports for v3 validation
from validation import validate_message

import boto3
from boto3.dynamodb.conditions import Attr
# Setup logger
logger = logging.getLogger()
logger.setLevel(logging.WARNING)

logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('nose').setLevel(logging.WARNING)

# Get the service resource.
DYNAMODB = boto3.resource('dynamodb')
USERS_TABLE = DYNAMODB.Table('users')

# To simplify this sample Lambda, we omit validation of access tokens and retrieval of a specific
# user's appliances. Instead, this array includes a variety of virtual appliances in v2 API syntax,
# and will be used to demonstrate transformation between v2 appliances and v3 endpoints.
APPLIANCE = [
    {
        "applianceId": "endpoint-001",
        "manufacturerName": "Smart Doorman",
        "modelName": "Smart Camera",
        "version": "1",
        "friendlyName": "Smart Camera",
        "friendlyDescription": "Camera that tells you what's there using machine learning",
        "isReachable": True,
        "actions": [
            "retrieveCameraStreamUri"
        ],
        "additionalApplianceDetails": {}
    }
]


def lambda_handler(request, context):
    """Main Lambda handler.

    Since you can expect both v2 and v3 directives for a period of time during the migration
    and transition of your existing users, this main Lambda handler must be modified to support
    both v2 and v3 requests.
    """
    if 'directive' not in request:
        return
    try:
        logger.info("Directive:")
        logger.info(json.dumps(request, indent=4, sort_keys=True))

        version = get_directive_version(request)

        if version == "3":
            logger.info("Received v3 directive!")
            if request["directive"]["header"]["name"] == "Discover":
                response = handle_discovery_v3(request)
            else:
                response = handle_non_discovery_v3(request)

        else:
            logger.info("Received v2 directive!")
            if request["header"]["namespace"] == "Alexa.ConnectedHome.Discovery":
                response = handle_discovery()
            else:
                response = handle_non_discovery(request)

        logger.info("Response:")
        logger.info(json.dumps(response, indent=4, sort_keys=True))

        if version == "3":
            logger.info("Validate v3 response")
            validate_message(request, response)

        return response
    except KeyError as error:
        logger.error(error)
    except ValueError as error:
        logger.error(error)
        raise

# v2 handlers


def handle_discovery():
    header = {
        "namespace": "Alexa.ConnectedHome.Discovery",
        "name": "DiscoverAppliancesResponse",
        "payloadVersion": "2",
        "messageId": get_uuid()
    }
    payload = {
        "discoveredAppliances": APPLIANCE
    }
    response = {
        "header": header,
        "payload": payload
    }
    return response


def handle_non_discovery(request):
    request_name = request["header"]["name"]

    if request_name == "TurnOnRequest":
        header = {
            "namespace": "Alexa.ConnectedHome.Control",
            "name": "TurnOnConfirmation",
            "payloadVersion": "2",
            "messageId": get_uuid()
        }
        payload = {}
    elif request_name == "TurnOffRequest":
        header = {
            "namespace": "Alexa.ConnectedHome.Control",
            "name": "TurnOffConfirmation",
            "payloadVersion": "2",
            "messageId": get_uuid()
        }
    # other handlers omitted in this example
    payload = {}
    response = {
        "header": header,
        "payload": payload
    }
    return response

# v2 utility functions


def get_appliance_by_appliance_id(appliance_id):
    for appliance in APPLIANCE:
        if appliance["applianceId"] == appliance_id:
            return appliance
    return None


def get_utc_timestamp(seconds=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S.00Z", time.gmtime(seconds))


def get_uuid():
    return str(uuid.uuid4())

# v3 handlers


def handle_discovery_v3(request):
    endpoints = []
    for appliance in APPLIANCE:
        endpoints.append(get_endpoint_from_v2_appliance(appliance))

    response = {
        "event": {
            "header": {
                "namespace": "Alexa.Discovery",
                "name": "Discover.Response",
                "payloadVersion": "3",
                "messageId": get_uuid()
            },
            "payload": {
                "endpoints": endpoints
            }
        }
    }
    return response


def handle_non_discovery_v3(request):
    request_namespace = request["directive"]["header"]["namespace"]
    request_name = request["directive"]["header"]["name"]
    if request_namespace == "Alexa":
        if request_name == "ReportState":
            return {
                "context": {
                    "properties": [
                        {
                            "namespace": "Alexa.EndpointHealth",
                            "name": "connectivity",
                            "value": {
                                "value": "OK"
                            },
                            "timeOfSample": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                            "uncertaintyInMilliseconds": 200
                        },
                    ]
                },
                "event": {
                    "header": {
                        "namespace": "Alexa",
                        "name": "StateReport",
                        "payloadVersion": "3",
                        "messageId": get_uuid(),
                        "correlationToken": request["directive"]["header"]["correlationToken"]
                    },
                    "endpoint": {
                        "scope": {
                            "type": "BearerToken",
                            "token": request['directive']['endpoint']['scope']['token']
                        },
                        "endpointId": "endpoint-001"
                    },
                    "payload": {}
                }
            }

    elif request_namespace == "Alexa.PowerController":
        if request_name == "TurnOn":
            value = "ON"
        else:
            value = "OFF"

        response = {
            "context": {
                "properties": [
                    {
                        "namespace": "Alexa.PowerController",
                        "name": "powerState",
                        "value": value,
                        "timeOfSample": get_utc_timestamp(),
                        "uncertaintyInMilliseconds": 500
                    }
                ]
            },
            "event": {
                "header": {
                    "namespace": "Alexa",
                    "name": "Response",
                    "payloadVersion": "3",
                    "messageId": get_uuid(),
                    "correlationToken": request["directive"]["header"]["correlationToken"]
                },
                "endpoint": {
                    "scope": {
                        "type": "BearerToken",
                        "token": request['directive']['endpoint']['scope']['token']
                    },
                    "endpointId": request["directive"]["endpoint"]["endpointId"]
                },
                "payload": {}
            }
        }
        return response

    elif request_namespace == "Alexa.Authorization":
        if request_name == "AcceptGrant":
            response = {
                "event": {
                    "header": {
                        "namespace": "Alexa.Authorization",
                        "name": "AcceptGrant.Response",
                        "payloadVersion": "3",
                        "messageId": get_uuid()
                    },
                    "payload": {}
                }
            }
            return response

    elif request_namespace == "Alexa.CameraStreamController":
        if request_name == "InitializeCameraStreams":
            value = "OK"
        logger.info('Attempting to lookup user')
        # very important to keep this token a secret in every layer
        bearer_token = request['directive']['endpoint']['scope']['token']
        user = USERS_TABLE.scan(FilterExpression=Attr(
            'stream_token').eq(bearer_token)).get('Items')
        if not user:
            return {
                "event": {
                    "header": {
                        "namespace": "Alexa",
                        "name": "ErrorResponse",
                        "messageId": get_uuid(),
                        "correlationToken": request['directive']['header']['correlationToken'],
                        "payloadVersion": "3"
                    },
                    "endpoint": {
                        "endpointId": "endpoint-001"
                    },
                    "payload": {
                        "type": "INVALID_AUTHORIZATION_CREDENTIAL",
                        "message": "Unable to reach endpoint 01 because the authorization was incorrect!"
                    }
                }
            }
        user = user[0]
        client_endpoint = urlparse(user['client_endpoint']['url'])
        stream_uri = 'rtsp://{0}:8554/live'.format(client_endpoint.hostname)
        response = {
            "context": {
                "properties": [
                    {
                        "namespace": "Alexa.EndpointHealth",
                        "name": "connectivity",
                        "value": {
                            "value": "OK"
                        },
                        "timeOfSample": datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                        "uncertaintyInMilliseconds": 200
                    }
                ]
            },
            "event": {
                "header": {
                    "namespace": "Alexa.CameraStreamController",
                    "name": "Response",
                    "payloadVersion": "3",
                    "messageId": get_uuid(),
                    "correlationToken": request['directive']['header']['correlationToken']
                },
                "endpoint": {
                    "scope": {
                        "type": "BearerToken",
                        "token": bearer_token
                    },
                    "endpointId": "endpoint-001"
                },
                "payload": {
                    "cameraStreams": [
                        {
                            "uri": stream_uri,
                            "expirationTime": "2019-09-27T20:30:30.45Z",
                            "idleTimeoutSeconds": 300,
                            "protocol": "RTSP",
                            "resolution": {
                                "width": 640,
                                "height": 480
                            },
                            "authorizationType": "NONE",
                            "videoCodec": "H264",
                            "audioCodec": "NONE"
                        }
                    ],
                    "imageUri": "http://{0}:{1}@{2}:{3}/frame".format(user['client_endpoint']['username'],
                                                                      user['client_endpoint']['password'],
                                                                      client_endpoint.hostname,
                                                                      client_endpoint.port)
                }
            }
        }
        return response

    # other handlers omitted in this example
    else:
        logger.error('RESPONSE NOT IS NOT SENT %s', str(request))
# v3 utility functions


def get_endpoint_from_v2_appliance(appliance):
    endpoint = {
        "endpointId": appliance["applianceId"],
        "manufacturerName": appliance["manufacturerName"],
        "friendlyName": appliance["friendlyName"],
        "description": appliance["friendlyDescription"],
        "displayCategories": [],
        "cookie": appliance["additionalApplianceDetails"],
        "capabilities": []
    }
    endpoint["displayCategories"] = get_display_categories_from_v2_appliance(
        appliance)
    endpoint["capabilities"] = get_capabilities_from_v2_appliance(appliance)
    return endpoint


def get_directive_version(request):
    try:
        return request["directive"]["header"]["payloadVersion"]
    except:
        try:
            return request["header"]["payloadVersion"]
        except:
            return "-1"


def get_endpoint_by_endpoint_id(endpoint_id):
    appliance = get_appliance_by_appliance_id(endpoint_id)
    if appliance:
        return get_endpoint_from_v2_appliance(appliance)
    return None


def get_display_categories_from_v2_appliance(appliance):
    model_name = appliance["modelName"]
    if model_name == "Smart Switch":
        displayCategories = ["SWITCH"]
    elif model_name == "Smart Light":
        displayCategories = ["LIGHT"]
    elif model_name == "Smart White Light":
        displayCategories = ["LIGHT"]
    elif model_name == "Smart Thermostat":
        displayCategories = ["THERMOSTAT"]
    elif model_name == "Smart Lock":
        displayCategories = ["SMARTLOCK"]
    elif model_name == "Smart Scene":
        displayCategories = ["SCENE_TRIGGER"]
    elif model_name == "Smart Activity":
        displayCategories = ["ACTIVITY_TRIGGER"]
    elif model_name == "Smart Camera":
        displayCategories = ["CAMERA"]
    else:
        displayCategories = ["OTHER"]
    return displayCategories


def get_capabilities_from_v2_appliance(appliance):
    model_name = appliance["modelName"]
    if model_name == "Smart Camera":
        capabilities = [
            {
                "type": "AlexaInterface",
                "interface": "Alexa.CameraStreamController",
                "version": "3",
                "cameraStreamConfigurations": [{
                    "protocols": ["RTSP"],
                    "resolutions": [{"width": 640, "height": 480}],
                    "authorizationTypes": ["NONE"],
                    "videoCodecs": ["H264"],
                    "audioCodecs": ["AAC"]
                }]
            }
        ]
    else:
        # in this example, just return simple on/off capability
        capabilities = [
            {
                "type": "AlexaInterface",
                "interface": "Alexa.PowerController",
                "version": "3",
                "properties": {
                    "supported": [
                        {"name": "powerState"}
                    ],
                    "proactivelyReported": True,
                    "retrievable": True
                }
            }
        ]

    # additional capabilities that are required for each endpoint
    endpoint_health_capability = {
        "type": "AlexaInterface",
        "interface": "Alexa.EndpointHealth",
        "version": "3",
        "properties": {
            "supported": [
                {"name": "connectivity"}
            ],
            "proactivelyReported": True,
            "retrievable": True
        }
    }
    alexa_interface_capability = {
        "type": "AlexaInterface",
        "interface": "Alexa",
        "version": "3"
    }
    capabilities.append(endpoint_health_capability)
    capabilities.append(alexa_interface_capability)
    return capabilities
