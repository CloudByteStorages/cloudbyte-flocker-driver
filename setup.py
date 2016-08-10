# Copyright 2016 CloudByte Inc
# See LICENSE file for details.

from setuptools import find_packages, setup

setup(
    name='cloudbyte-flocker-driver',
    version='1.0',
    description="CloudByte Backend Plugin for ClusterHQ/Flocker ",
    author='Yogesh Prasad',
    author_email='yogesh.prasad@cloudbyte.com',
    packages=find_packages(),
    license='Apache 2.0',
    zip_safe=False,
    keywords=['cloudbyte', 'flocker', 'docker', 'driver', 'python'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Plugins',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'License :: OSI Approved :: Apache 2.0',
        'Programming Language :: Python :: 2.7',
    ],
)
