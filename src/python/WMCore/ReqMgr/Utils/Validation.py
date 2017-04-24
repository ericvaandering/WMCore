"""
ReqMgr request handling.

"""
from __future__ import print_function
import json
import time
import logging

from WMCore.WMSpec.WMWorkload import WMWorkloadHelper
from WMCore.WMSpec.WMWorkloadTools import loadSpecClassByType, setArgumentsWithDefault
from WMCore.REST.Auth import authz_match
from WMCore.WMFactory import WMFactory
from WMCore.Services.DBS.DBS3Reader import DBS3Reader as DBSReader
from WMCore.ReqMgr.Auth import getWritePermission
from WMCore.ReqMgr.DataStructs.Request import initialize_request_args, initialize_resubmission, initialize_clone
from WMCore.ReqMgr.DataStructs.RequestStatus import check_allowed_transition, STATES_ALLOW_ONLY_STATE_TRANSITION
from WMCore.ReqMgr.DataStructs.RequestError import InvalidStateTransition, InvalidSpecParameterValue
from WMCore.ReqMgr.Tools.cms import releases, architectures, dashboardActivities
from WMCore.Lexicon import procdataset


def loadRequestSchema(workload, requestSchema):
    """
    _loadRequestSchema_
    Legacy code to support ops script

    Does modifications to the workload I don't understand
    Takes a WMWorkloadHelper, operates on it directly with the schema
    """
    schema = workload.data.request.section_('schema')
    for key, value in requestSchema.iteritems():
        if isinstance(value, dict) and key == 'LumiList':
            value = json.dumps(value)
        try:
            setattr(schema, key, value)
        except Exception as ex:
            # Attach TaskChain tasks
            if isinstance(value, dict) and requestSchema['RequestType'] == 'TaskChain' and 'Task' in key:
                newSec = schema.section_(key)
                for k, v in requestSchema[key].iteritems():
                    if isinstance(value, dict) and key == 'LumiList':
                        value = json.dumps(value)
                    try:
                        setattr(newSec, k, v)
                    except Exception as ex:
                        # this logging need to change to cherry py logging
                        logging.error("Invalid Value: %s", str(ex))
            else:
                # this logging need to change to cherry py logging
                logging.error("Invalid Value: %s", str(ex))

    schema.timeStamp = int(time.time())
    schema = workload.data.request.schema

    # might belong in another method to apply existing schema
    workload.data.owner.Group = schema.Group
    workload.data.owner.Requestor = schema.Requestor


def workqueue_stat_validation(request_args):
    stat_keys = ['total_jobs', 'input_lumis', 'input_events', 'input_num_files']
    return set(request_args.keys()) == set(stat_keys)


def validate_request_update_args(request_args, config, reqmgr_db_service, param):
    """
    param and safe structure is RESTArgs structure: named tuple
    RESTArgs(args=[], kwargs={})

    validate post/put request
    1. read data from body
    2. validate the permission (authentication)
    3. validate state transition (against previous state from couchdb)
    2. validate using workload validation
    3. convert data from body to arguments (spec instance, argument with default setting)

    TODO: raise right kind of error with clear message
    """
    # this needs to be deleted for validation
    request_name = request_args.pop("RequestName")
    couchurl = '%s/%s' % (config.couch_host, config.couch_reqmgr_db)
    workload = WMWorkloadHelper()
    workload.loadSpecFromCouch(couchurl, request_name)

    # first validate the permission by status and request type.
    # if the status is not set only ReqMgr Admin can change the values
    # TODO for each step, assigned, approved, announce find out what other values
    # can be set
    request_args["RequestType"] = workload.requestType()
    permission = getWritePermission(request_args)
    authz_match(permission['role'], permission['group'])
    del request_args["RequestType"]

    # validate the status
    if "RequestStatus" in request_args:
        validate_state_transition(reqmgr_db_service, request_name, request_args["RequestStatus"])
        if request_args["RequestStatus"] in STATES_ALLOW_ONLY_STATE_TRANSITION:
            # if state change doesn't allow other transition nothing else to validate
            args_only_status = {}
            args_only_status["RequestStatus"] = request_args["RequestStatus"]
            args_only_status["cascade"] = request_args.get("cascade", False)
            return workload, args_only_status
        elif request_args["RequestStatus"] == 'assigned':
            workload.validateArgumentForAssignment(request_args)

    # TODO: fetch it from the assignment arg definition
    if 'RequestPriority' in request_args:
        request_args['RequestPriority'] = int(request_args['RequestPriority'])
        if (lambda x: (x >= 0 and x < 1e6))(request_args['RequestPriority']) is False:
            raise InvalidSpecParameterValue("RequestPriority must be an integer between 0 and 1e6")

    return workload, request_args


def validate_request_create_args(request_args, config, reqmgr_db_service, *args, **kwargs):
    """
    *arg and **kwargs are only for the interface
    validate post request
    1. read data from body
    2. validate using spec validation
    3. convert data from body to arguments (spec instance, argument with default setting)
    TODO: raise right kind of error with clear message
    """

    initialize_request_args(request_args, config)
    # check the permission for creating the request
    permission = getWritePermission(request_args)
    authz_match(permission['role'], permission['group'])

    # load the correct class to in order to validate the arguments
    specClass = loadSpecClassByType(request_args["RequestType"])

    if request_args["RequestType"] == "Resubmission":
        # do not set default values for Resubmission since it will be inherited from parent
        # both create & assign args are accepted for Resubmission creation
        initialize_resubmission(request_args, reqmgr_db_service)
    else:
        # set default values for the request_args
        setArgumentsWithDefault(request_args, specClass.getWorkloadCreateArgs())

    spec = specClass()
    workload = spec.factoryWorkloadConstruction(request_args["RequestName"],
                                                request_args)

    return workload, request_args

def validate_clone_create_args(request_args, config, reqmgr_db_service, *args, **kwargs):
    """
    *arg and **kwargs are only for the interface
    validate post request
    1. read data from body
    2. validate using spec validation
    3. convert data from body to arguments (spec instance, argument with default setting)
    TODO: raise right kind of error with clear message
    """
    cloned_args = initialize_clone(request_args, reqmgr_db_service)
    initialize_request_args(cloned_args, config)
    # check the permission for creating the request
    permission = getWritePermission(cloned_args)
    authz_match(permission['role'], permission['group'])

    # TODO: Do validation only one request_args

    spec = loadSpecClassByType(cloned_args["RequestType"])()
    # for clone validation will be skiped in factoryWorkloadConstruction
    workload = spec.factoryWorkloadConstruction(cloned_args["RequestName"],
                                                    cloned_args)

    return workload, cloned_args


def validate_state_transition(reqmgr_db_service, request_name, new_state):
    """
    validate state transition by getting the current data from
    couchdb
    """
    requests = reqmgr_db_service.getRequestByNames(request_name)
    # generator object can't be subscribed: need to loop.
    # only one row should be returned
    for request in requests.values():
        current_state = request["RequestStatus"]
    if not check_allowed_transition(current_state, new_state):
        raise InvalidStateTransition(current_state, new_state)
    return


def create_json_template_spec(specArgs):
    template = {}
    for key, prop in specArgs.items():

        if key == "RequestorDN":
            # this will be automatically collected so skip it.
            continue

        if key == "CMSSWVersion":
            # get if from tag collector
            value = releases()
        elif key == "ScramArch":
            value = architectures()
        elif prop == "Dashboard":
            value = dashboardActivities()
        elif prop.get("optional", True):
            # if optional need to always have default value
            value = prop["default"]
        else:
            value = "REPLACE-%s" % key
        template[key] = value
    return template


def get_request_template_from_type(request_type, loc="WMSpec.StdSpecs"):
    pluginFactory = WMFactory("specArgs", loc)
    alteredClassName = "%sWorkloadFactory" % request_type
    spec = pluginFactory.loadObject(classname=request_type, alteredClassName=alteredClassName)
    specArgs = spec.getWorkloadCreateArgs()

    result = create_json_template_spec(specArgs)
    return result


def validateOutputDatasets(outDsets, dbsUrl):
    """
    Validate output datasets after all the other arguments have been
    locally update during assignment.
    """
    if len(outDsets) != len(set(outDsets)):
        msg = "Output dataset contains duplicates and it has to be fixed! %s" % outDsets
        raise InvalidSpecParameterValue(msg)

    datatier = []
    for dataset in outDsets:
        procds, tier = dataset.split("/")[2:]
        datatier.append(tier)
        try:
            procdataset(procds)
        except AssertionError as ex:
            msg = "Bad output dataset name, check the processed dataset name.\n %s" % str(ex)
            raise InvalidSpecParameterValue(msg)

    # Verify whether the output datatiers are available in DBS
    _validateDatatier(datatier, dbsUrl)


def _validateDatatier(datatier, dbsUrl):
    """
    _validateDatatier_

    Provided a list of datatiers extracted from the outputDatasets, checks
    whether they all exist in DBS.
    """
    dbsTiers = DBSReader.listDatatiers(dbsUrl)
    badTiers = list(set(datatier) - set(dbsTiers))
    if badTiers:
        raise InvalidSpecParameterValue("Bad datatier(s): %s not available in DBS." % badTiers)
