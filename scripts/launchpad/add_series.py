#!/usr/bin/python2
# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2016 Canonical Ltd
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

import os

from launchpadlib import launchpad


def add_series_target(task, series):
    for related_task in task.related_tasks:
        if related_task.target == xenial:
            return related_task
    else:
        return task.bug.addTask(target=xenial)


cachedir = os.path.join(os.getenv('HOME'), '.launchpadlib', 'cache')
client = launchpad.Launchpad.login_with(
    'snapcraft scripts', 'production', cachedir, version='devel')

ubuntu = client.distributions['ubuntu']
xenial = ubuntu.getSeries(name_or_version='xenial')
yakkety = ubuntu.getSeries(name_or_version='yakkety')

snapcraft = client.projects['snapcraft']
snapcraft_milestone = snapcraft.getMilestone(name='2.12')
xenial_updates_milestone = ubuntu.getMilestone(name='xenial-updates')
tasks = snapcraft.searchTasks(milestone=snapcraft_milestone)

for task in tasks:
    xenial_task = add_series_target(task, xenial)
    xenial_task.milestone = xenial_updates_milestone
    xenial_task.lp_save()
    add_series_target(task, yakkety)
