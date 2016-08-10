#CloudByte Flocker Plugin

##Installation

 Each of the following packages needs to be installed on every Flocker Node

* Open-iSCSI
     
  * Ubuntu
    
    sudo apt-get install open-iscsi
    	
  * Centos
    
    sudo yum install iscsi-initiator-utils

* CloudByte Flocker Plugin
   ```
    git clone https://github.com/yogeshprasad/cloudbyte-flocker-driver.git 
    cd cloudbyte-flocker-driver
    sudo /opt/flocker/bin/python2.7 setup.py install
   ``` 

##Configuration
 
This plugin reads configuration from /etc/flocker/agent.yml config file.
To use this plugin you need to create till VSM in ElastiCenter and provide the necessary
information in configuration file. Find the sample configuration below.

* Minimum configuration, Uses the default QoS properties to create storage volume
```
"version": 1
"control-service":
   "hostname": "20.10.112.92"
   "port": 4524
"dataset":
   "backend": "cloudbyte_flocker_driver"
   "elasticenter_ip": "20.10.200.200"
   "apikey": "oWMsdot2OmW3aRyuQayJwMX6F0pIpPy5D-tH8NhCUE8Q39IApeFHgWEzXvC78YGPv1m3c2ME4DqQutFcao6ijA"
   "vsm_name": "VSM1"
   "account_name": "Account1"
   ```
* Optional configuration to create storage volume with QoS properties
```
"version": 1
"control-service":
   "hostname": "20.10.112.92"
   "port": 4524
"dataset":
   "backend": "cloudbyte_flocker_driver"
   "elasticenter_ip": "20.10.200.200"
   "apikey": "oWMsdot2OmW3aRyuQayJwMX6F0pIpPy5D-tH8NhCUE8Q39IApeFHgWEzXvC78YGPv1m3c2ME4DqQutFcao6ijA"
   "vsm_name": "VSM1"
   "account_name": "Account1"
   "profiles": {'gold': '10000', 'silver': '5000', 'bronze': '1000'}
```   
* All supported configuration by driver
```
"version": 1
"control-service":
   "hostname": "20.10.112.92"
   "port": 4524
"dataset":
   "backend": "cloudbyte_flocker_driver"
   "elasticenter_ip": "20.10.200.200"
   "apikey": "oWMsdot2OmW3aRyuQayJwMX6F0pIpPy5D-tH8NhCUE8Q39IApeFHgWEzXvC78YGPv1m3c2ME4DqQutFcao6ijA"
   "vsm_name": "VSM1"
   "account_name": "Account1"
   "profiles": {'gold': '10000', 'silver': '5000', 'bronze': '1000'}
   "confirm_volume_create_retry_interval": 5
   "confirm_volume_create_retries": 10
   "confirm_volume_delete_retry_interval": 5
   "confirm_volume_delete_retries": 10
   "add_qosgroup": {'iops': '100', 'latency': '15', 'graceallowed': 'false',
                    'networkspeed': '0', 'memlimit': '0', 'tpcontrol': 'false',
                    'throughput': '0', 'iopscontrol': 'true' }
   "create_volume": {'blocklength': '512B', 'compression': 'off', 'deduplication': 'off',
                     'sync': 'always', 'recordsize': '16k', 'protocoltype': 'ISCSI'}
```
#####After installing the plugin and setting up your configuration restart the flocker agent service.

#Support
Please file bugs/issues at the Github issues page. For Flocker related questions/issues contact the Flocker team at [Google Groups](https://groups.google.com/forum/#!forum/flocker-users). The code and documentation in this module are released with no warranties or SLAs and are intended to be supported via the Open Source community.
