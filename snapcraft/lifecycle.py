# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2015 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import contextlib
import logging
import os
import shutil
import subprocess
import tarfile

import yaml

import snapcraft
import snapcraft.yaml

from snapcraft import (
    common,
    meta,
    pluginhandler,
    repo,
)
from snapcraft.lxd import Cleanbuilder
from snapcraft.common import format_snap_name


logger = logging.getLogger(__name__)


_TEMPLATE_YAML = r'''name: # the name of the snap
version: # the version of the snap
summary: # 79 char long summary
description: # A longer description for the snap
'''


def init():
    """Initialize a snapcraft project."""

    if os.path.exists('snapcraft.yaml'):
        raise EnvironmentError('snapcraft.yaml already exists!')
    yaml = _TEMPLATE_YAML.strip()
    with open('snapcraft.yaml', mode='w+') as f:
        f.write(yaml)
    logger.info('Created snapcraft.yaml.')


def execute(step, project_options, part_names=None):
    """Execute until step in the lifecycle for part_names or all parts.

    Lifecycle execution will happen for each step iterating over all
    the available parts, if part_names is specified, only those parts
    will run.

    If one of the parts to execute has an after keyword, execution is
    forced until the stage step for such part. If part_names was provided
    and after is not in this set, an exception will be raised.

    :param str step: A valid step in the lifecycle: pull, build, strip or snap.
    :param project_options: Runtime options for the project.
    :param list part_names: A list of parts to execute the lifecycle on.
    :raises RuntimeError: If a prerequesite of the part needs to be staged
                          and such part is not in the list of parts to iterate
                          over.
    :returns: A dict with the snap name, version, type and architectures.
    """
    config = snapcraft.yaml.load_config(project_options)
    repo.install_build_packages(config.build_tools)

    _Executor(config).run(step, part_names)

    return {'name': config.data['name'],
            'version': config.data['version'],
            'arch': config.data['architectures'],
            'type': config.data.get('type', '')}


class _Executor:

    def __init__(self, config):
        self.config = config

    def run(self, step, part_names=None, recursed=False):
        if part_names:
            self.config.validate_parts(part_names)
            parts = {p for p in self.config.all_parts if p.name in part_names}
        else:
            parts = self.config.all_parts
            part_names = self.config.part_names

        dirty = {p.name for p in parts if p.should_step_run('stage')}
        step_index = common.COMMAND_ORDER.index(step) + 1

        for step in common.COMMAND_ORDER[0:step_index]:
            if step == 'stage':
                pluginhandler.check_for_collisions(self.config.all_parts)
            for part in parts:
                self._run_step(step, part, part_names, dirty, recursed)

        self._create_meta(step, part_names)

    def _run_step(self, step, part, part_names, dirty, recursed):
        common.reset_env()
        prereqs = self.config.part_prereqs(part.name)
        if recursed:
            prereqs = prereqs & dirty
        if prereqs and not prereqs.issubset(part_names):
            for prereq in self.config.all_parts:
                if prereq.name in prereqs and prereq.should_step_run('stage'):
                    raise RuntimeError(
                        'Requested {!r} of {!r} but there are unsatisfied '
                        'prerequisites: {!r}'.format(
                            step, part.name, ' '.join(prereqs)))
        elif prereqs:
            # prerequisites need to build all the way to the staging
            # step to be able to share the common assets that make them
            # a dependency.
            logger.info(
                '{!r} has prerequisites that need to be staged: '
                '{}'.format(part.name, ' '.join(prereqs)))
            self.run('stage', prereqs, recursed=True)

        if not part.should_step_run(step):
            part.notify_part_progress('Skipping {}'.format(step),
                                      '(already ran)')
            return

        # Run the preparation function for this step (if implemented)
        with contextlib.suppress(AttributeError):
            getattr(part, 'prepare_{}'.format(step))()

        common.env = self.config.build_env_for_part(part)
        getattr(part, step)()

    def _create_meta(self, step, part_names):
        if step == 'strip' and part_names == self.config.part_names:
            common.env = self.config.snap_env()
            meta.create(self.config.data)


def _create_tar_filter(tar_filename):
    def _tar_filter(tarinfo):
        fn = tarinfo.name
        if fn.startswith('./parts/') and not fn.startswith('./parts/plugins'):
            return None
        elif fn in ('./stage', './snap', tar_filename):
            return None
        elif fn.endswith('.snap'):
            return None
        return tarinfo
    return _tar_filter


def cleanbuild(project_options):
    if not repo.is_package_installed('lxd'):
        raise EnvironmentError(
            'The lxd package is not installed, in order to use `cleanbuild` '
            'you must install lxd onto your system. Refer to the '
            '"Ubuntu Desktop and Ubuntu Server" section on '
            'https://linuxcontainers.org/lxd/getting-started-cli/'
            '#ubuntu-desktop-and-ubuntu-server to enable a proper setup.')

    config = snapcraft.yaml.load_config(project_options)
    tar_filename = '{}_{}_source.tar.bz2'.format(
        config.data['name'], config.data['version'])

    with tarfile.open(tar_filename, 'w:bz2') as t:
        t.add(os.path.curdir, filter=_create_tar_filter(tar_filename))

    snap_filename = format_snap_name(config.data)
    Cleanbuilder(snap_filename, tar_filename, project_options).execute()


def _snap_data_from_dir(directory):
    with open(os.path.join(directory, 'meta', 'snap.yaml')) as f:
        snap = yaml.load(f)

    return {'name': snap['name'],
            'version': snap['version'],
            'arch': snap.get('architectures', []),
            'type': snap.get('type', '')}


def snap(project_options, directory=None, output=None):
    if directory:
        snap_dir = os.path.abspath(directory)
        snap = _snap_data_from_dir(snap_dir)
    else:
        # make sure the full lifecycle is executed
        snap_dir = common.get_snapdir()
        snap = execute('strip', project_options)

    snap_name = output or format_snap_name(snap)

    logger.info('Snapping {}'.format(snap_name))
    # These options need to match the review tools:
    # http://bazaar.launchpad.net/~click-reviewers/click-reviewers-tools/trunk/view/head:/clickreviews/common.py#L38
    mksquashfs_args = ['-noappend', '-comp', 'xz', '-no-xattrs']
    if snap['type'] != 'os':
        mksquashfs_args.append('-all-root')

    subprocess.check_call(
        ['mksquashfs', snap_dir, snap_name] + mksquashfs_args)
    logger.info('Snapped {}'.format(snap_name))


def _reverse_dependency_tree(config, part_name):
    dependents = config.part_dependents(part_name)
    for dependent in dependents.copy():
        # No need to worry about infinite recursion due to circular
        # dependencies since the YAML validation won't allow it.
        dependents |= _reverse_dependency_tree(config, dependent)

    return dependents


def _clean_part_and_all_dependents(config, part, staged_state, stripped_state,
                                   step):
    # Clean the part in question
    part.clean(staged_state, stripped_state, step)

    # Now obtain the reverse dependency tree for this part. Make sure
    # all dependents are also cleaned.
    dependents = _reverse_dependency_tree(config, part.name)
    dependent_parts = {p for p in config.all_parts
                       if p.name in dependents}
    for dependent_part in dependent_parts:
        dependent_part.clean(staged_state, stripped_state, step)


def _remove_directory_if_empty(directory):
    if os.path.isdir(directory) and not os.listdir(directory):
        os.rmdir(directory)


def _cleanup_common_directories(config):
    _remove_directory_if_empty(common.get_partsdir())
    _remove_directory_if_empty(common.get_stagedir())
    _remove_directory_if_empty(common.get_snapdir())

    max_index = -1
    for part in config.all_parts:
        step = part.last_step()
        if step:
            index = common.COMMAND_ORDER.index(step)
            if index > max_index:
                max_index = index

    # If no parts have been pulled, remove the parts directory. In most cases
    # this directory should have already been cleaned, but this handles the
    # case of a failed pull. Note however that the presence of local plugins
    # should prevent this removal.
    if (max_index < common.COMMAND_ORDER.index('pull') and
            os.path.exists(common.get_partsdir()) and not
            os.path.exists(common.get_local_plugindir())):
        logger.info('Cleaning up parts directory')
        shutil.rmtree(common.get_partsdir())

    # If no parts have been staged, remove staging area.
    should_remove_stagedir = max_index < common.COMMAND_ORDER.index('stage')
    if should_remove_stagedir and os.path.exists(common.get_stagedir()):
        logger.info('Cleaning up staging area')
        shutil.rmtree(common.get_stagedir())

    # If no parts have been stripped, remove snapping area.
    should_remove_snapdir = max_index < common.COMMAND_ORDER.index('strip')
    if should_remove_snapdir and os.path.exists(common.get_snapdir()):
        logger.info('Cleaning up snapping area')
        shutil.rmtree(common.get_snapdir())


def clean(parts, step=None):
    config = snapcraft.yaml.load_config()

    if parts:
        config.validate_parts(parts)

    staged_state = config.get_project_state('stage')
    stripped_state = config.get_project_state('strip')

    for part in config.all_parts:
        if not parts:
            part.clean(staged_state, stripped_state, step)
        elif part.name in parts:
            _clean_part_and_all_dependents(
                config, part, staged_state, stripped_state, step)

    _cleanup_common_directories(config)
