# Copyright 2013-2019 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import pytest

import contextlib
import os.path
import sys

import jsonschema

import llnl.util.cpu
import spack.paths

# This is needed to check that with repr we could create equivalent objects
from llnl.util.cpu import MicroArchitecture  # noqa


@pytest.fixture(params=[
    'linux-ubuntu18.04-broadwell',
    'linux-rhel7-broadwell',
    'linux-rhel7-skylake_avx512',
    'linux-rhel7-ivybridge',
    'linux-rhel7-haswell',
    'linux-rhel7-zen',
    'linux-centos7-power8',
    'darwin-mojave-ivybridge',
    'darwin-mojave-broadwell'
])
def expected_target(request, monkeypatch):
    platform, operating_system, target = request.param.split('-')

    architecture_family = llnl.util.cpu.targets[target].architecture_family
    monkeypatch.setattr(
        llnl.util.cpu.platform, 'machine', lambda: str(architecture_family)
    )

    # Monkeypatch for linux
    if platform == 'linux':
        monkeypatch.setattr(llnl.util.cpu.platform, 'system', lambda: 'Linux')

        @contextlib.contextmanager
        def _open(not_used_arg):
            filename = os.path.join(
                spack.paths.test_path, 'data', 'targets', request.param
            )
            with open(filename) as f:
                yield f

        monkeypatch.setattr(llnl.util.cpu, 'open', _open, raising=False)

    elif platform == 'darwin':
        monkeypatch.setattr(llnl.util.cpu.platform, 'system', lambda: 'Darwin')

        filename = os.path.join(
            spack.paths.test_path, 'data', 'targets', request.param
        )
        info = {}
        with open(filename) as f:
            for line in f:
                key, value = line.split(':')
                info[key.strip()] = value.strip()

        def _check_output(args):
            current_key = args[-1]
            return info[current_key]

        monkeypatch.setattr(llnl.util.cpu, 'check_output', _check_output)

    return llnl.util.cpu.targets[target]


@pytest.fixture(params=[x for x in llnl.util.cpu.targets])
def supported_target(request):
    return request.param


def test_target_detection(expected_target):
    detected_target = llnl.util.cpu.detect_host()
    assert detected_target == expected_target


def test_no_dashes_in_target_names(supported_target):
    assert '-' not in supported_target


def test_str_conversion(supported_target):
    assert supported_target == str(llnl.util.cpu.targets[supported_target])


def test_repr_conversion(supported_target):
    target = llnl.util.cpu.targets[supported_target]
    assert eval(repr(target)) == target


def test_equality(supported_target):
    target = llnl.util.cpu.targets[supported_target]

    for name, other_target in llnl.util.cpu.targets.items():
        if name == supported_target:
            assert other_target == target
        else:
            assert other_target != target


@pytest.mark.parametrize('target,other_target,err_cls', [
    (llnl.util.cpu.targets['x86'],
     llnl.util.cpu.targets['skylake'],
     ValueError),
    (llnl.util.cpu.targets['bulldozer'],
     llnl.util.cpu.targets['skylake'],
     ValueError),
    pytest.param(
        llnl.util.cpu.targets['x86_64'], 'foo', TypeError,
        marks=pytest.mark.xfail(
            sys.version_info < (3, 0),
            reason="Unorderable types comparison doesn't raise in Python 2"
        )
    ),
])
def test_partial_ordering_failures(target, other_target, err_cls):
    with pytest.raises(err_cls):
        target < other_target


@pytest.mark.parametrize('target,operation,other_target', [
    (llnl.util.cpu.targets['x86_64'], '<', llnl.util.cpu.targets['skylake']),
    (llnl.util.cpu.targets['icelake'], '>', llnl.util.cpu.targets['skylake']),
    (llnl.util.cpu.targets['piledriver'], '<=', llnl.util.cpu.targets['zen']),
    (llnl.util.cpu.targets['zen2'], '>=', llnl.util.cpu.targets['zen']),
    (llnl.util.cpu.targets['zen'], '>=', llnl.util.cpu.targets['zen'])
])
def test_partial_ordering(target, operation, other_target):
    code = 'target' + operation + 'other_target'
    assert eval(code)


@pytest.mark.parametrize('target_name,expected_family', [
    ('skylake', 'x86_64'),
    ('zen', 'x86_64'),
    ('pentium2', 'x86'),
])
def test_architecture_family(target_name, expected_family):
    target = llnl.util.cpu.targets[target_name]
    assert str(target.architecture_family) == expected_family


@pytest.mark.parametrize('target_name,feature', [
    ('skylake', 'avx2'),
    ('icelake', 'avx512f'),
    # Test feature aliases
    ('icelake', 'avx512'),
    ('skylake', 'sse3'),
    ('power8', 'altivec'),
    ('broadwell', 'sse4.1'),
])
def test_features_query(target_name, feature):
    target = llnl.util.cpu.targets[target_name]
    assert feature in target


def test_generic_microarchitecture():
    generic_march = llnl.util.cpu.generic_microarchitecture('foo')

    assert generic_march.name == 'foo'
    assert not generic_march.features
    assert not generic_march.ancestors
    assert generic_march.vendor == 'generic'


def test_target_json_schema():
    # The file targets.json contains static data i.e. data that is not meant to
    # be modified by users directly. It is thus sufficient to validate it
    # only once during unit tests.
    json_data = llnl.util.cpu._targets_json.data
    jsonschema.validate(json_data, llnl.util.cpu.schema)


@pytest.mark.parametrize('target_name,compiler,version,expected_flags', [
    ('x86_64', 'gcc', '4.9.3', '-march=x86-64 -mtune=x86-64'),
    ('nocona', 'gcc', '4.9.3', '-march=nocona -mtune=nocona'),
    ('nehalem', 'gcc', '4.9.3', '-march=nehalem -mtune=nehalem'),
    ('nehalem', 'gcc', '4.8.5', '-march=corei7 -mtune=corei7'),
    ('sandybridge', 'gcc', '4.8.5', '-march=corei7-avx -mtune=corei7-avx'),
    # Test that an unknown compiler returns an empty string
    ('sandybridge', 'unknown', '4.8.5', ''),
])
def test_optimization_flags(target_name, compiler, version, expected_flags):
    target = llnl.util.cpu.targets[target_name]
    flags = target.optimization_flags(compiler, version)
    assert flags == expected_flags


@pytest.mark.parametrize('target_name,compiler,version', [
    ('excavator', 'gcc', '4.8.5')
])
def test_unsupported_optimization_flags(target_name, compiler, version):
    target = llnl.util.cpu.targets[target_name]
    with pytest.raises(
            llnl.util.cpu.UnsupportedMicroArchitecture,
            matches='cannot produce optimized binary'
    ):
        target.optimization_flags(compiler, version)