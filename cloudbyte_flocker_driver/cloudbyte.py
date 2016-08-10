# Copyright 2016 CloudByte Inc
# See LICENSE file for details.

import threading
import time
import socket
import shlex
import uuid
import six
import json
import subprocess
import os.path

from six.moves import http_client
from six.moves import urllib
from bitmath import GiB, MiB
from zope.interface import implementer
from twisted.python import filepath
from flocker.node.agents.blockdevice import (
    IBlockDeviceAPI, BlockDeviceVolume, UnknownVolume, AlreadyAttachedVolume,
    UnattachedVolume,IProfiledBlockDeviceAPI,
)

ALLOCATION_UNIT = GiB(1).bytes

@implementer(IBlockDeviceAPI)
@implementer(IProfiledBlockDeviceAPI)
class CloudByteBlockDeviceAPI(object):
    def __init__(self, cluster_id, **kwargs):
        self.cluster_id = cluster_id
        self.cb_tsm_name = kwargs.get('vsm_name', None)
        self.cb_account_name = kwargs.get('account_name', None)
        self.cb_apikey = kwargs.get('apikey', None)
        self.san_ip = kwargs.get('elasticenter_ip', None)
     
        self.cb_confirm_volume_create_retry_interval = kwargs.get('confirm_volume_create_retry_interval', 5)
        self.cb_confirm_volume_create_retries = kwargs.get('confirm_volume_create_retries', 10)
        self.cb_confirm_volume_delete_retry_interval = kwargs.get('confirm_volume_delete_retry_interval', 5)
        self.cb_confirm_volume_delete_retries = kwargs.get('confirm_volume_delete_retries', 10)
        self.cb_add_qosgroup = kwargs.get('add_qosgroup', {  'iops': '100', 'latency': '15', 'graceallowed': 'false',
                                                                'networkspeed': '0', 'memlimit': '0', 'tpcontrol': 'false',
                                                                'throughput': '0', 'iopscontrol': 'true' })
        self.cb_create_volume = kwargs.get('create_volume', {'blocklength': '512B', 'compression': 'off', 'deduplication': 'off',
                                                                'sync': 'always', 'recordsize': '16k', 'protocoltype': 'ISCSI'})
        self.profiles = self._set_profiles(kwargs.get('profiles', None))
        self._verify_basic_configuration(self.cb_tsm_name, self.cb_account_name, self.cb_apikey, self.san_ip)

    def _verify_basic_configuration(self, cb_tsm_name, cb_account_name, cb_apikey, san_ip):
        err_msg = "Unable to initialize CloudByte Plugin. Missing configuration: "
        
        if not cb_tsm_name:
            raise Exception(err_msg + "vsm_name")
        if not cb_account_name:
            raise Exception(err_msg + "account_name")
        if not cb_apikey:
            raise Exception(err_msg + "apikey")
        if not san_ip:
            raise Exception(err_msg + "elasticenter_ip")
    
    def _set_profiles(self, user_profiles):
        profiles = {'gold': '10000', 'silver': '500', 'bronze': '100'}

        if user_profiles:
            profiles = user_profiles
        return profiles

    def _path_exists(self, path, counter=1):
        for i in xrange(counter):
            if os.path.exists(path):
                return True
            time.sleep(2)
        return False

    def _get_expected_disk_path(self, ip, iqn):
        return '/dev/disk/by-path/ip-%s:3260-iscsi-%s-lun-0' % (ip,
                                                       iqn) 
    def _get_device_file_from_path(self, disk_by_path):
        device = None
        if os.path.exists(disk_by_path):
            device = os.readlink(disk_by_path)
        return device.replace('../../', '/dev/')

    def _iscsi_logout(self, tgt_ip, tgt_iqn):
        cmd = 'sudo iscsiadm -m node -p %s -T %s -u' % (tgt_ip, tgt_iqn)
        subprocess.check_output(shlex.split(cmd))
    
        cmd = 'sudo iscsiadm -m node -o delete -T %s' % (tgt_iqn)
        subprocess.check_output(shlex.split(cmd))

    def _iscsi_login(self, tgt_ip, tgt_iqn):
        attached_at = None
        path = self._get_expected_disk_path(tgt_ip, tgt_iqn)
        cmd = 'sudo iscsiadm -m node -p %s -T %s --login' % (tgt_ip, tgt_iqn)
        subprocess.check_output(shlex.split(cmd))
        if self._path_exists(path, 5):
            attached_at = path
        
        if not attached_at:
            msg = ("Failed iSCSI login to device: [" +path+"].")
            raise UnknownVolume(msg)
        
        return attached_at

    def _iscsi_discovery(self, portal):
        cmd = 'sudo iscsiadm -m discovery -t sendtargets -p %s' % portal
        output = subprocess.check_output(shlex.split(cmd))
        return output.split('\n')

    def _get_volume_size_in_bypes(self, size):
        return MiB(int(size)).bytes
        
    def _get_volume_size_in_gb(self, size):
        size = int(size)/ALLOCATION_UNIT
        return str(int(size))+'G'

    def _get_url(self, cmd, params, apikey):
        """Will prepare URL that connects to CloudByte."""

        if params is None:
            params = {}

        params['command'] = cmd
        params['response'] = 'json'

        sanitized_params = {}

        for key in params:
            value = params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        url = ('/client/api?%s' % sanitized_params)
        
        # Add the apikey
        api = {}
        api['apiKey'] = apikey
        url = url + '&' + urllib.parse.urlencode(api)

        return url

    def _extract_http_error(self, error_data):
        # Extract the error message from error_data
        error_msg = ""

        # error_data is a single key value dict
        for key, value in error_data.items():
            error_msg = value.get('errortext')

        return error_msg

    def _execute_and_get_response_details(self, host, url):
        """Will prepare response after executing an http request."""

        res_details = {}
        try:
            # Prepare the connection
            connection = http_client.HTTPSConnection(host)
            # Make the connection
            connection.request('GET', url)
            # Extract the response as the connection was successful
            response = connection.getresponse()
            # Read the response
            data = response.read()
            # Transform the json string into a py object
            data = json.loads(data)
            # Extract http error msg if any
            error_details = None
            if response.status != 200:
                error_details = self._extract_http_error(data)

            # Prepare the return object
            res_details['data'] = data
            res_details['error'] = error_details
            res_details['http_status'] = response.status

        finally:
            connection.close()

        return res_details

    def _api_request_for_cloudbyte(self, cmd, params, version=None):
        """Make http calls to CloudByte."""
        
        # Below is retrieved from /etc/cinder/cinder.conf
        apikey = self.cb_apikey

        if apikey is None:
            msg = ("API key is missing for CloudByte driver.")
            raise UnknownVolume(msg)

        host = self.san_ip

        # Construct the CloudByte URL with query params
        url = self._get_url(cmd, params, apikey)

        data = {}
        error_details = None
        http_status = None

        try:
            # Execute CloudByte API & frame the response
            res_obj = self._execute_and_get_response_details(host, url)

            data = res_obj['data']
            error_details = res_obj['error']
            http_status = res_obj['http_status']

        except http_client.HTTPException as ex:
            msg = ("Error executing CloudByte API ["+cmd+"], "
                     "Error: "+ex+". URL [" +str(url)+ "].")
            raise UnknownVolume(msg)

        # Check if it was an error response from CloudByte
        if http_status != 200:
            msg = ("Failed to execute CloudByte API ["+cmd+"]." 
                     " Http status: "+str(http_status)+","
                     " Error: "+str(error_details)+"URL [" +str(url)+ "].")
            raise UnknownVolume(msg)

        return data

    def _get_account_id_from_name(self, account_name):
        params = {}
        data = self._api_request_for_cloudbyte("listAccount", params)
        accounts = data["listAccountResponse"]["account"]

        account_id = None
        for account in accounts:
            if account.get("name") == account_name:
                account_id = account.get("id")
                break

        if account_id is None:
            msg = ("Failed to get CloudByte account details "
                    "for account ["+account_name+"].")
            raise UnknownVolume(msg)

        return account_id

    def _request_tsm_details(self, account_id):
        params = {"accountid": account_id}

        # List all CloudByte tsm
        data = self._api_request_for_cloudbyte("listTsm", params)
        return data

    def _get_tsm_details(self, data, tsm_name, account_name):
        # Filter required tsm's details
        tsms = data['listTsmResponse'].get('listTsm')

        if tsms is None:
            msg = ("TSM ["+tsm_name+"] was not found in CloudByte storage "
                   "for account ["+account_name+"].")
            raise ValueError(msg)

        tsmdetails = {}
        for tsm in tsms:
            if tsm['name'] == tsm_name:
                tsmdetails['datasetid'] = tsm['datasetid']
                tsmdetails['tsmid'] = tsm['id']
                break

        return tsmdetails

    def _add_qos_group_request(self, tsmid, volume_name,
                               qos_group_params, profile_name):
        # Prepare the user input params
        params = {
            "name": "QoS_" + volume_name,
            "tsmid": tsmid
        }

        # Override the default configuration by qos specs
        if qos_group_params:
            params.update(qos_group_params)
            
        if profile_name:
            iops = self.profiles.get(profile_name)
            if not iops:
                msg = ("Requested profile not found ["+profile_name+"].")
                raise UnknownVolume(msg)

            profile = {'iops': iops}
            params.update(profile)
        
        data = self._api_request_for_cloudbyte("addQosGroup", params)
        return data

    def _create_volume_request(self, size, datasetid, qosgroupid,
                               tsmid, volume_name, file_system_params):       

        # Prepare the user input params
        params = {
            "datasetid": datasetid,
            "name": volume_name,
            "qosgroupid": qosgroupid,
            "tsmid": tsmid,
            "quotasize": self._get_volume_size_in_gb(size)
        }

        # Override the default configuration by qos specs
        if file_system_params:
            params.update(file_system_params)

        data = self._api_request_for_cloudbyte("createVolume", params)
        return data

    def _queryAsyncJobResult_request(self, jobid):
        async_cmd = "queryAsyncJobResult"
        params = {
            "jobId": jobid,
        }
        data = self._api_request_for_cloudbyte(async_cmd, params)
        return data

    def _retry_volume_operation(self, operation, jobid):
        """CloudByte async calls via the FixedIntervalLoopingCall."""

        # Query the CloudByte storage with this jobid
        volume_response = self._queryAsyncJobResult_request(jobid)

        result_res = None
        if volume_response is not None:
            result_res = volume_response.get('queryasyncjobresultresponse')

        if result_res is None:
            msg = (
                "Null response received while querying "
                "for ["+operation+"] based job ["+jobid+"] "
                "at CloudByte storage.")
            raise ValueError(msg)

        return result_res

    def _wait_for_volume_creation(self, volume_response, cb_volume_name):
        """Given the job wait for it to complete."""

        vol_res = volume_response.get('createvolumeresponse')

        if vol_res is None:
            msg = ("Null response received while creating volume ["+cb_volume_name+"] "
                    "at CloudByte storage.")
            raise ValueError(msg)

        jobid = vol_res.get('jobid')

        if jobid is None:
            msg = ("Job id not found in CloudByte's "
                    "create volume ["+cb_volume_name+"] response.")
            raise ValueError(msg)

        retry_interval = (
            self.cb_confirm_volume_create_retry_interval)

        max_retries = (
            self.cb_confirm_volume_create_retries)
        retries = 0
        
        for retries in range(0, max_retries):
            result_res = self._retry_volume_operation('Create Volume', jobid)
            
            status = result_res.get('jobstatus')
            if status == 1:
                break
            elif status == 2:
                job_result = result_res.get("jobresult")
                err_msg = job_result.get("errortext")
                err_code = job_result.get("errorcode")
                msg = (
                    "Error in Operation [Create Volume] "
                    "for volume ["+cb_volume_name+"] in CloudByte "
                    "storage: ["+err_msg+"], "
                    "error code: ["+err_code+"].")
                raise ValueError(msg)
            
            elif retries == max_retries - 1:
                # All attempts exhausted
                msg = ("CloudByte operation [%(operation)s] failed"
                              " for volume ["+cb_volume_name+"]. Exhausted all"
                              " ["+max_retries+"] attempts.")
                raise ValueError(msg)

            time.sleep(retry_interval)

    def _get_iscsi_service_id_from_response(self, volume_id, data):
        iscsi_service_res = data.get('listVolumeiSCSIServiceResponse')

        if iscsi_service_res is None:
            msg = ("Null response received from CloudByte's "
                    "list volume iscsi service.")
            raise ValueError(msg)

        iscsi_service_list = iscsi_service_res.get('iSCSIService')

        if iscsi_service_list is None:
            msg = ('No iscsi services found in CloudByte storage.')
            raise ValueError(msg)

        iscsi_id = None

        for iscsi_service in iscsi_service_list:
            if iscsi_service['volume_id'] == volume_id:
                iscsi_id = iscsi_service['id']
                break

        if iscsi_id is None:
            msg = ("No iscsi service found for CloudByte "
                        "volume ["+volume_id+"].")
            raise ValueError(msg)
        else:
            return iscsi_id

    def _get_initiator_group_id_from_response(self, data, filter):
        """Find iSCSI initiator group id."""

        ig_list_res = data.get('listInitiatorsResponse')

        if ig_list_res is None:
            msg = ("Null response received from CloudByte's "
                        "list iscsi initiators.")
            raise ValueError(msg)

        ig_list = ig_list_res.get('initiator')

        if ig_list is None:
            msg = ('No iscsi initiators were found in CloudByte.')
            raise ValueError(msg)

        ig_id = None

        for ig in ig_list:
            if ig.get('initiatorgroup') == filter:
                ig_id = ig['id']
                break

        return ig_id

    def _request_update_iscsi_service(self, iscsi_id, ig_id):
        params = {
            "id": iscsi_id,
            "igid": ig_id
        }

        self._api_request_for_cloudbyte(
            'updateVolumeiSCSIService', params)

    def _search_volume_id(self, cb_volumes, cb_volume_id):
        """Search the volume in CloudByte."""

        volumes_res = cb_volumes.get('listFilesystemResponse')

        if volumes_res is None:
            msg = ("No response was received from CloudByte's "
                    "list filesystem api call.")
            raise ValueError(msg)

        volumes = volumes_res.get('filesystem')

        if volumes is None:
            msg = ("No volume was found at CloudByte storage.")
            raise ValueError(msg)

        volume_id = None

        for vol in volumes:
            if vol['id'] == cb_volume_id:
                volume_id = vol['id']
                break

        return volume_id
    
    def _search_volume_id_by_name(self, cb_volumes, cb_volume_name):
        """Search the volume in CloudByte."""

        volumes_res = cb_volumes.get('listFilesystemResponse')

        if volumes_res is None:
            msg = ("No response was received from CloudByte's "
                    "list filesystem api call.")
            raise ValueError(msg)

        volumes = volumes_res.get('filesystem')

        if volumes is None:
            msg = ("No volume was found at CloudByte storage.")
            raise ValueError(msg)

        volume_id = None

        for vol in volumes:
            if vol['name'] == cb_volume_name:
                volume_id = vol['id']
                break

        if not volume_id:
            msg = ("Volume not found at CloudByte. "
                    "Volumes [" +str(cb_volumes)+ "]. "
                    "Accepted volume name [" +cb_volume_name+"].")
            raise ValueError(msg)
        
        return volume_id

    def _search_volume(self, cb_volumes, cb_volume_id):
        """Search the volume in CloudByte."""

        volumes_res = cb_volumes.get('listFilesystemResponse')

        if volumes_res is None:
            msg = ("No response was received from CloudByte's "
                    "list filesystem api call.")
            raise ValueError(msg)

        volumes = volumes_res.get('filesystem')

        if volumes is None:
            msg = ("No volume was found at CloudByte storage.")
            raise ValueError(msg)

        volume = None

        for vol in volumes:
            if vol['id'] == cb_volume_id:
                volume = vol
                break

        if not volume:
            msg = ("Volume was not found at CloudByte storage. "
                   "Accepted volume ["+cb_volume_id+"]. "
                   "Volumes ["+str(cb_volumes)+"].")
            raise ValueError(msg)

        return volume

    def _update_initiator_group(self, volume_id, ig_name):

        # Get account id of this account
        account_name = self.cb_account_name
        account_id = self._get_account_id_from_name(account_name)

        # Fetch the initiator group ID
        params = {"accountid": account_id}

        iscsi_initiator_data = self._api_request_for_cloudbyte(
            'listiSCSIInitiator', params)

        # Filter the list of initiator groups with the name
        ig_id = self._get_initiator_group_id_from_response(
            iscsi_initiator_data, ig_name)

        params = {"storageid": volume_id}

        iscsi_service_data = self._api_request_for_cloudbyte(
            'listVolumeiSCSIService', params)
        iscsi_id = self._get_iscsi_service_id_from_response(
            volume_id, iscsi_service_data)

        # Update the iscsi service with above fetched iscsi_id
        self._request_update_iscsi_service(iscsi_id, ig_id)

    def _wait_for_volume_deletion(self, volume_response, cb_volume_id):
        """Given the job wait for it to complete."""

        vol_res = volume_response.get('deleteFileSystemResponse')

        if vol_res is None:
            msg = ("Null response received while deleting volume ["+cb_volume_id+"] "
                    "at CloudByte storage.")
            raise ValueError(msg)

        jobid = vol_res.get('jobid')

        if jobid is None:
            msg = ("Job id not found in CloudByte's "
                    "delete volume ["+cb_volume_id+"] response.")
            raise ValueError(msg)

        retry_interval = (
            self.cb_confirm_volume_delete_retry_interval)

        max_retries = (
            self.cb_confirm_volume_delete_retries)

        retries = 0
        
        for retries in range(0, max_retries):
            result_res = self._retry_volume_operation('Delete Volume', jobid)
            
            status = result_res.get('jobstatus')
            if status == 1:
                break
            elif status == 2:
                job_result = result_res.get("jobresult")
                err_msg = job_result.get("errortext")
                err_code = job_result.get("errorcode")
                msg = (
                      "Error in Operation [Delete Volume] "
                      "for volume ["+cb_volume_id+"] in CloudByte "
                      "storage: ["+err_msg+"], "
                      "error code: ["+err_code+"].")
                raise ValueError(msg)
            
            elif retries == max_retries - 1:
                # All attempts exhausted
                msg = ("CloudByte operation [%(operation)s] failed"
                              " for volume ["+cb_volume_id+"]. Exhausted all"
                              " ["+max_retries+"] attempts.")
                raise ValueError(msg)
                
            time.sleep(retry_interval)

    def compute_instance_id(self):
        return unicode(socket.gethostbyname(socket.getfqdn()))

    def create_volume(self, dataset_id, size):
        return self.create_volume_with_profile(dataset_id, size, None)

    def create_volume_with_profile(self, dataset_id, size, profile_name):
        # Get account id of this account
        account_id = self._get_account_id_from_name(self.cb_account_name)

        # Set backend storage volume name using OpenStack volume id
        cb_volume_name = str(dataset_id)

        tsm_data = self._request_tsm_details(account_id)
        tsm_details = self._get_tsm_details(tsm_data, self.cb_tsm_name, self.cb_account_name)

        qos_data = self._add_qos_group_request(tsm_details.get('tsmid'), cb_volume_name, self.cb_add_qosgroup, profile_name)

        # Extract the qos group id from response
        qosgroupid = qos_data['addqosgroupresponse']['qosgroup']['id']

        # Send a create volume request to CloudByte API
        vol_data = self._create_volume_request(
            size, tsm_details.get('datasetid'), qosgroupid,
            tsm_details.get('tsmid'), cb_volume_name, self.cb_create_volume)

        # Since create volume is an async call;
        # need to confirm the creation before proceeding further
        self._wait_for_volume_creation(vol_data, cb_volume_name)

        # Fetch iscsi id
        cb_volumes = self._api_request_for_cloudbyte(
            'listFileSystem', params={})
        volume_id = self._search_volume_id_by_name(cb_volumes,
                                                      cb_volume_name)
        vol = self._search_volume(cb_volumes, volume_id)

        params = {"storageid": volume_id}

        iscsi_service_data = self._api_request_for_cloudbyte(
            'listVolumeiSCSIService', params)
        iscsi_id = self._get_iscsi_service_id_from_response(
            volume_id, iscsi_service_data)

        # Fetch the initiator group ID
        params = {"accountid": account_id}

        iscsi_initiator_data = self._api_request_for_cloudbyte(
            'listiSCSIInitiator', params)
        ig_id = self._get_initiator_group_id_from_response(
            iscsi_initiator_data, 'ALL')

        # Update the iscsi service with above fetched iscsi_id & ig_id
        self._request_update_iscsi_service(iscsi_id, ig_id)
        
        return BlockDeviceVolume(
            blockdevice_id=unicode(volume_id),
            size=size,
            attached_to=None,
            dataset_id=dataset_id)

    def destroy_volume(self, cb_volume_id):
        if cb_volume_id is not None:

            cb_volumes = self._api_request_for_cloudbyte(
                'listFileSystem', {})

            # Search cb_volume_id in CloudByte volumes
            # incase it has already been deleted from CloudByte
            cb_volume_id = self._search_volume_id(cb_volumes, cb_volume_id)

            # Delete volume at CloudByte
            if cb_volume_id is not None:
                # Need to set the initiator group to None before deleting
                self._update_initiator_group(cb_volume_id, 'None')

                params = {"id": cb_volume_id}
                del_res = self._api_request_for_cloudbyte('deleteFileSystem',
                                                          params)

                self._wait_for_volume_deletion(del_res, cb_volume_id)
  
        return

    def get_device_path(self, cb_volume_id):
        cb_volumes = self._api_request_for_cloudbyte(
            'listFileSystem', {})

        vol = self._search_volume(cb_volumes, cb_volume_id)

        disk_by_path = self._get_expected_disk_path(vol['ipaddress'], vol['iqnname'])
        return filepath.FilePath(
            self._get_device_file_from_path(disk_by_path)).realpath()

    def attach_volume(self, cb_volume_id, attach_to):
        cb_volumes = self._api_request_for_cloudbyte(
            'listFileSystem', {})

        vol = self._search_volume(cb_volumes, cb_volume_id)

        if not vol:
            raise UnknownVolume(cb_volume_id)
        
        tgt_ip = vol['ipaddress']
        tgt_iqn = vol['iqnname']
        path = self._get_expected_disk_path(tgt_ip, tgt_iqn)
        
        if not self._path_exists(path, 2):
            targets = self._iscsi_discovery(vol['ipaddress'])
            if len(targets) < 1 and vol['iqnname'] not in targets:
                raise Exception("No targes found during discovery.")
            
            self._iscsi_login(vol['ipaddress'], vol['iqnname'])

        return BlockDeviceVolume(
            blockdevice_id=unicode(cb_volume_id),
            size=self._get_volume_size_in_bypes(vol['currentTotalSpace']),
            attached_to=attach_to,
            dataset_id=uuid.UUID(vol['name']))

    def detach_volume(self, cb_volume_id):
        cb_volumes = self._api_request_for_cloudbyte(
            'listFileSystem', {})

        # Search cb_volume_id in CloudByte volumes
        # incase it has already been deleted from CloudByte
        vol = self._search_volume(cb_volumes, cb_volume_id)

        if not vol:
            raise UnknownVolume(cb_volume_id)

        tgt_iqn = vol['iqnname']
        svip = vol['ipaddress']
        path = self._get_expected_disk_path(svip, tgt_iqn)
        if not self._path_exists(path, 2):
            raise UnattachedVolume(cb_volume_id)
        self._iscsi_logout(svip, tgt_iqn)

    def list_volumes(self):
        account_id = self._get_account_id_from_name(self.cb_account_name)
        tsm_data = self._request_tsm_details(account_id)
        tsm_details = self._get_tsm_details(tsm_data, self.cb_tsm_name, self.cb_account_name)
        
        volumes = []
        cb_volumes_res = self._api_request_for_cloudbyte(
            'listFileSystem', {})

        volumes_res = cb_volumes_res.get('listFilesystemResponse')

        if volumes_res is None:
            msg = ("No response was received from CloudByte's list filesystem api call.")
            raise ValueError(msg)
        
        cb_volumes = volumes_res.get('filesystem')

        if cb_volumes: 
            for v in cb_volumes:
                if v['Tsmid'] == tsm_details['tsmid']:
                    attached_to = None
                    path = self._get_expected_disk_path(v['ipaddress'], v['iqnname'])
                    if self._path_exists(path, 1):
                        attached_to = self.compute_instance_id()
                    volumes.append(BlockDeviceVolume(
                                   blockdevice_id=unicode(v['id']),
                                   size=self._get_volume_size_in_bypes(v['currentTotalSpace']),
                                   attached_to=attached_to,
                                   dataset_id=uuid.UUID(str(v['name']))))
        return volumes
    
    def allocation_unit(self):
        return ALLOCATION_UNIT

def cloudbyte_from_configuration(cluster_id, **kwargs):
    return CloudByteBlockDeviceAPI(str(cluster_id), **kwargs)
