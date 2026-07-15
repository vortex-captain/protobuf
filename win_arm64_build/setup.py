#! /usr/bin/env python
"""setuptools build for the protobuf win_arm64 (cp311-abi3) wheel.

Copied into the assembled build tree by build_wheel.py. Derived from
python/dist/setup.py, with the changes required to build natively on Windows
ARM64 with MSVC instead of the Bazel/mingw cross-compile:

  * Windows link args: the upstream '-static' is an mingw (libgcc) flag that MSVC
    rejects, so it is dropped on Windows.
  * abi3 / limited API: the extension is compiled with Py_LIMITED_API for Python
    3.11 and marked py_limited_api=True, so the wheel is tagged cp311-abi3 and
    links against python3.lib -- matching the upstream win_amd64 wheel, which is
    also abi3.
  * Native MSVC does not understand GCC __attribute__ (message.c has an unguarded
    __attribute__((flatten))), so msvc_compat.h is force-included to neutralize it.
"""

import glob
import os
import sys

from setuptools import Extension, find_namespace_packages, setup


def GetVersion():
  with open(os.path.join('google', 'protobuf', '__init__.py')) as version_file:
    file_globals = {}
    exec(version_file.read(), file_globals)  # pylint:disable=exec-used
    return file_globals['__version__']


# abi3 target: Python 3.11 => 0x030b0000. Loadable on CPython 3.11+.
LIMITED_API_VERSION = 0x030B0000

current_dir = os.path.dirname(os.path.abspath(__file__))
extra_link_args = []
extra_compile_args = []
define_macros = [('Py_LIMITED_API', hex(LIMITED_API_VERSION))]

if not sys.platform.startswith('win'):
  extra_compile_args = ['-fvisibility=hidden']
else:
  extra_compile_args = ['/FI' + os.path.join(current_dir, 'msvc_compat.h')]

fasttable_decoder_enabled = False

srcs = (
    glob.glob('google/protobuf/*.c')
    + glob.glob('python/*.c')
    + glob.glob('upb/**/*.c', recursive=True)
    + glob.glob('utf8_range/*.c')
)

if not fasttable_decoder_enabled:
  srcs = list(filter(lambda src: 'decode_fast' not in src, srcs))

setup(
    name='protobuf',
    version=GetVersion(),
    description='Protocol Buffers',
    download_url='https://github.com/protocolbuffers/protobuf/releases',
    long_description="Protocol Buffers are Google's data interchange format",
    url='https://developers.google.com/protocol-buffers/',
    project_urls={
        'Source': 'https://github.com/protocolbuffers/protobuf',
    },
    maintainer='protobuf@googlegroups.com',
    maintainer_email='protobuf@googlegroups.com',
    license='BSD-3-Clause',
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
    ],
    packages=find_namespace_packages(include=['google*']),
    install_requires=[],
    ext_modules=[
        Extension(
            'google._upb._message',
            srcs,
            include_dirs=[current_dir, os.path.join(current_dir, 'utf8_range')],
            language='c',
            extra_link_args=extra_link_args,
            extra_compile_args=extra_compile_args,
            define_macros=define_macros,
            py_limited_api=True,
        )
    ],
    python_requires='>=3.11',
)
