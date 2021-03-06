# Components.py - Abstract class for any Lustre filesystem components.
# Copyright (C) 2010-2013 CEA
#
# This file is part of shine
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#

from itertools import ifilter, groupby
from operator import attrgetter

from ClusterShell.NodeSet import NodeSet

# Constants for component states
(MOUNTED,    \
 EXTERNAL,   \
 RECOVERING, \
 OFFLINE,    \
 INPROGRESS, \
 CLIENT_ERROR, \
 TARGET_ERROR, \
 RUNTIME_ERROR) = range(8)

from Shine.Lustre import ComponentError
from Shine.Lustre.Server import ServerGroup
from Shine.Lustre.Actions.Status import Status
from Shine.Lustre.Actions.Execute import Execute

class Component(object):
    """
    Abstract class for all common part of all Lustre filesystem 
    components.
    """

    # Text name for this component
    TYPE = "(should be overridden)"

    # Each component knows which component it depends on.
    # Its start order should be this component start order + 1.
    # This value will be use to sort the components when starting.
    START_ORDER = 0

    # Order used when displaying a list of components
    DISPLAY_ORDER = 0

    # Text mapping for each possible states
    STATE_TEXT_MAP = {}

    def __init__(self, fs, server, enabled = True, mode = 'managed'):

        # File system
        self.fs = fs

        # Each component resides on one server
        self.server = server

        # Status
        self.state = None

        # Enabled or not
        self.action_enabled = enabled

        # List of running action
        self.__running_actions = []

        # Component behaviour change depending on its mode.
        self._mode = mode

    @property
    def label(self):
        """
        Return the component label. 
        It contains the filesystem name and component type.
        """
        return "%s-%s" % (self.fs.fs_name, self.TYPE)

    def allservers(self):
        """
        Return all servers this target can run on. On standard component
        there is only one server.
        """
        return ServerGroup([self.server])

    def uniqueid(self):
        """Return a unique string representing this component."""
        return "%s-%s" % (self.label, ','.join(self.server.nids))

    def longtext(self):
        """
        Return a string describing this component, for output purposes.
        """
        return self.label

    def update(self, other):
        """
        Update my serializable fields from other/distant object.
        """
        self.state = other.state

    def __getstate__(self):
        odict = self.__dict__.copy()
        del odict['fs']
        return odict

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.fs = None

    #
    # Component behaviour
    #
  
    def capable(self, action):
        # Do I implement this method?
        #XXX: Presently, the check do not check this is callable.
        # This is used for testing 'label' by example.
        return hasattr(self, action) 

    def is_external(self):
        return self._mode == 'external'
 
    # 
    # Component printing methods.
    #

    def text_statusonly(self):
        """
        Return a string version of the component state, only.
        """
        return Component.text_status(self)

    def text_status(self):
        """
        Return a human text form for the component state.
        """
        return self.STATE_TEXT_MAP.get(self.state, "BUG STATE %s" % self.state)


    #
    def lustre_check(self):
        """
        Check component health at Lustre level.
        """
        raise NotImplemented("Component must implement this.")

    def full_check(self, mountdata=True):
        """
        Check component states, at Lustre level, and any other required ones.
        """
        self.lustre_check()

    #
    # Inprogress action methods
    #
    def _add_action(self, act):
        """
        Add the named action to the running action list.
        """
        assert(act not in self.__running_actions)
        self.__running_actions.append(act)

    def _del_action(self, act):
        """
        Remove the named action from the running action list.
        """
        self.__running_actions.remove(act)

    def _list_action(self):
        """
        Return the running action list.
        """
        return self.__running_actions

    #
    # Event raising methods
    #

    def action_start(self, act):
        """Called by Actions.* when starting"""
        self._add_action(act)
        self.fs.local_event(self.TYPE, act, 'start', comp=self)

    def action_progress(self, act, result):
        """Called by Actions.* when some progress info should be sent."""
        self.fs.local_event(self.TYPE, act, 'progress',
                            comp=self, result=result)

    def action_done(self, act, result=None):
        """Called by Actions.* when done"""
        self._del_action(act)
        self.fs.local_event(self.TYPE, act, 'done', comp=self, result=result)

    def action_timeout(self, act):
        """Called by Actions.* on timeout"""
        self._del_action(act)
        self.fs.local_event(self.TYPE, act, 'timeout', comp=self)

    def action_failed(self, act, result):
        """Called by Actions.* on failure"""
        self._del_action(act)
        self.fs.local_event(self.TYPE, act, 'failed', comp=self, result=result)

    #
    # Helper methods to check component state in Actions.
    #

    def is_started(self):
        """Return True if the component is started."""
        return self.state == MOUNTED

    def is_stopped(self):
        """Return True if the component is stopped."""
        return self.state == OFFLINE

    #
    # Component common actions
    #

    def status(self, **kwargs):
        """Check component status."""
        return Status(self, **kwargs)

    def execute(self, **kwargs):
        """Exec a custom command."""
        return Execute(self, **kwargs)


class ComponentGroup(object):
    """
    Gather and efficiently manipulate list of Components.
    """

    def __init__(self, iterable=None):
        self._elems = {}
        if iterable:
            self._elems = dict([(comp.uniqueid(), comp) for comp in iterable])

    def __len__(self):
        return len(self._elems)

    def __iter__(self):
        return self._elems.itervalues()

    def __contains__(self, comp):
        return comp.uniqueid() in self._elems

    def __getitem__(self, key):
        return self._elems[key]

    def __str__(self):
        return str(self.labels())

    def add(self, component):
        """
        Add a new component to the group. 
        
        Raises a KeyError if a component
        with the same uniqueid() is already added.
        """
        if component in self:
            raise KeyError("A component with id %s already exists." %
                           component.uniqueid())
        self._elems[component.uniqueid()] = component
 
    def update(self, iterable):
        """
        Insert all components from iterable.
        """
        for comp in iterable:
            self.add(comp)

    def __or__(self, other):
        """
        Implements the | operator. So s | t returns a new group with
        elements from both s and t.
        """
        if not isinstance(other, ComponentGroup):
            return NotImplemented 
        grp = ComponentGroup()
        grp.update(iter(self))
        grp.update(iter(other))
        return grp

    #
    # Useful getters
    #

    def labels(self):
        """Return a NodeSet containing all component label."""
        return NodeSet.fromlist((comp.label for comp in self))

    def servers(self):
        """Return a NodeSet containing all component servers."""
        return NodeSet.fromlist((comp.server.hostname for comp in self))

    def allservers(self):
        """Return a NodeSet containing all component servers and fail
        servers."""
        servers = self.servers()
        for comp in self.filter(supports='failservers'):
            servers.update(comp.failservers.nodeset())
        return servers

    #
    # Filtering methods
    #

    def filter(self, supports=None, key=None):
        """
        Returns a new ComponentGroup instance containing only the component
        that matches the filtering rules.

        Your own filtering rule could be defined using the key argument.

        Example: Return only the OST from the group
        >>> group.filter(key=lambda t: t.TYPE == OST.TYPE)
        """
        if supports and not key:
            filter_key = lambda x: x.capable(supports)
        elif supports and key:
            filter_key = lambda x: key(x) and x.capable(supports)
        else:
            filter_key = key

        return ComponentGroup(ifilter(filter_key, iter(self)))

    def enabled(self):
        """Uses filter() to return only the enabled components."""
        key = attrgetter('action_enabled')
        return self.filter(key=key)

    def managed(self, supports=None):
        """Uses filter() to return only the enabled and managed components."""
        key = lambda comp: not comp.is_external() and comp.action_enabled
        return self.filter(supports, key=key)

    #
    # Grouping methods
    #

    def groupby(self, attr=None, key=None, reverse=False):
        """Return an iterator over the group components. 
        
        The component will be grouped using one of their attribute or using a
        custom key.
        
        Example #1: Group component by type
        >>> for comp_type, comp_list in group.groupby(attr='TYPE'):
        ...

        Example #2: Group component first by type, then by server
        >>> key = lambda t: (t.TYPE, t.server)
        >>> for comp_type, comp_list in group.groupby(key=key):
        ...
        """
        assert (not (attr and key)), "Unsupported: attr and supports"

        if key is None and attr is not None:
            key = attrgetter(attr)

        # Sort the components using the key, and then group results 
        # using the same key.
        sortlist = sorted(iter(self), key=key, reverse=reverse)
        grouped = groupby(sortlist, key)
        return ((grpkey, ComponentGroup(comps)) for grpkey, comps in grouped)

    def groupbyserver(self):
        """Uses groupby() to group component per server."""
        return self.groupby(attr='server')
