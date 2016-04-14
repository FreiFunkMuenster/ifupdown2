#!/usr/bin/python
#
# Copyright 2014 Cumulus Networks, Inc. All rights reserved.
# Author: Roopa Prabhu, roopa@cumulusnetworks.com
#
import json
import ifupdown.policymanager as policymanager

try:
    from ipaddr import IPNetwork
    from sets import Set
    from ifupdown.iface import *
    from ifupdownaddons.utilsbase import *
    from ifupdownaddons.modulebase import moduleBase
    from ifupdownaddons.iproute2 import iproute2
except ImportError, e:
    raise ImportError (str(e) + "- required module not found")

class ethtool(moduleBase,utilsBase):
    """  ifupdown2 addon module to configure ethtool attributes """

    _modinfo = {'mhelp' : 'ethtool configuration module for interfaces',
                'attrs': {
                      'link-speed' :
                            {'help' : 'set link speed',
                             'example' : ['link-speed 1000'],
                             'default' : 'varies by platform and port'},
                      'link-duplex' :
                            {'help': 'set link duplex',
                             'example' : ['link-duplex full'],
                             'validvals' : ['half', 'full'],
                             'default' : 'full'},
                      'link-autoneg' :
                            {'help': 'set autonegotiation',
                             'example' : ['link-autoneg on'],
                             'validvals' : ['on', 'off'],
                             'default' : 'varies by platform and port'}}}

    def __init__(self, *args, **kargs):
        moduleBase.__init__(self, *args, **kargs)
        self.ipcmd = None
        # keep a list of iface objects who have modified link attributes
        self.ifaceobjs_modified_configs = []

    def _post_up(self, ifaceobj, operation='post_up'):
        """
        _post_up and _pre_down will reset the layer 2 attributes to default policy
        settings.
        """
        if not self.ipcmd.link_exists(ifaceobj.name):
            return
        cmd = ''
        for attr in ['speed', 'duplex', 'autoneg']:
            # attribute existed before but we must reset to default
            config_val = ifaceobj.get_attr_value_first('link-%s'%attr)
            default_val = policymanager.policymanager_api.get_iface_default(
                module_name='ethtool',
                ifname=ifaceobj.name,
                attr='link-%s'%attr)

            if not default_val and not config_val:
                # there is no point in checking the running config
                # if we have no default and the user did not have settings
                continue
            # check running values
            running_val = self.get_running_attr(attr, ifaceobj)
            # we need to track if an interface has a configured value
            # this will be used if there are duplicate iface stanza and
            # the configured interface will always take precedence.
            # so even if we do not change the settings because they match
            # what is configured, we need to append it here so that later duplicate
            # ifaces will see that we had a configured iface and not change things.
            if config_val and config_val == running_val:
                # running value is what is configured, do nothing
                # this prevents unconfigured ifaces from resetting to default
                self.ifaceobjs_modified_configs.append(ifaceobj.name)
                continue

            if not config_val and default_val and default_val == running_val:
                # nothing configured but the default is running
                continue
            # if we are the oldest sibling, we have to reset to defaults
            # unless a previous sibling had link attr configured and made changes
            if ((ifaceobj.flags & iface.HAS_SIBLINGS) and
                (ifaceobj.flags & iface.OLDEST_SIBLING) and
                (ifaceobj.name in self.ifaceobjs_modified_configs)):
                continue

            # if we are not the oldest and we have no configs, do not change anything
            # the only way a non-oldest sibling would change values is if it
            # had configured settings
            if (not ((ifaceobj.flags & iface.HAS_SIBLINGS) and
                     (ifaceobj.flags & iface.OLDEST_SIBLING)) and
                not config_val):
                continue

            # if we got this far, we need to change it
            if config_val and (config_val != running_val):
                # if the configured value is not set, set it
                cmd += ' %s %s' % (attr, config_val)
            elif default_val and (default_val != running_val):
                # or if it has a default not equal to running value, set it
                cmd += ' %s %s' % (attr, default_val)
            else:
                # no value set nor default, leave it alone
                pass
        if cmd:
            try:
                # we should only be calling ethtool if there
                # is a speed set or we can find a default speed
                # because we should only be calling ethtool on swp ports
                # we also need to set this here in case we changed
                # something.  this prevents unconfigured ifaces from resetting to default
                self.ifaceobjs_modified_configs.append(ifaceobj.name)
                cmd = 'ethtool -s %s %s' %(ifaceobj.name, cmd)
                self.exec_command(cmd)
            except Exception, e:
                ifaceobj.status = ifaceStatus.ERROR
                self.log_warn('%s: %s' %(ifaceobj.name, str(e)))
        else:
            pass

    def _pre_down(self, ifaceobj):
        pass #self._post_up(ifaceobj,operation="_pre_down")

    def _query_check(self, ifaceobj, ifaceobjcurr):
        """
        _query_check() needs to compare the configured (or running)
        attribute with the running attribute.

        If there is nothing configured, we compare the default attribute with
        the running attribute and FAIL if they are different.
        This is because a reboot will lose their running attribute
        (the default will get set).
        """
        for attr in ['speed', 'duplex', 'autoneg']:
            configured = ifaceobj.get_attr_value_first('link-%s'%attr)
            # if there is nothing configured, do not check
            if not configured:
                continue
            default = policymanager.policymanager_api.get_iface_default(
                module_name='ethtool',
                ifname=ifaceobj.name,
                attr='link-%s'%attr)
            # if we have no default, do not bother checking
            # this avoids ethtool calls on virtual interfaces
            if not default:
                continue
            # autoneg comes from ethtool whereas speed and duplex from /sys/class
            running_attr = self.get_running_attr(attr, ifaceobj)
            if (not running_attr):
                continue

            # we make sure we can get a running value first
            if (running_attr and configured and running_attr == configured):
                # PASS since running is what is configured 
                ifaceobjcurr.update_config_with_status('link-%s'%attr,
                                                       running_attr, 0)
            elif (running_attr and configured and running_attr != configured):
                # We show a FAIL since it is not the configured or default
                ifaceobjcurr.update_config_with_status('link-%s'%attr,
                                                       running_attr, 1)
            elif (running_attr and default and running_attr == default):
                # PASS since running is default
                ifaceobjcurr.update_config_with_status('link-%s'%attr,
                                                       running_attr, 0)
            elif (default or configured):
                # We show a FAIL since it is not the configured or default
                ifaceobjcurr.update_config_with_status('link-%s'%attr,
                                                       running_attr, 1)
        return

    def get_autoneg(self,ethtool_output=None):
        """
        get_autoneg simply calls the ethtool command and parses out
        the autoneg value.
        """
        ethtool_attrs = ethtool_output.split()
        if ('Auto-negotiation:' in ethtool_attrs):
            return(ethtool_attrs[ethtool_attrs.index('Auto-negotiation:')+1])
        else:
            return(None)

    def get_running_attr(self,attr='',ifaceobj=None):
        if not ifaceobj or not attr:
            return
        running_attr = None
        try:
            if attr == 'autoneg':
                output=self.exec_commandl(['ethtool', ifaceobj.name])
                running_attr = self.get_autoneg(ethtool_output=output)
            else:
                running_attr = self.read_file_oneline('/sys/class/net/%s/%s' % \
                                                      (ifaceobj.name, attr))
        except:
            # for nonexistent interfaces, we get an error (rc = 256 or 19200)
            self.logger.debug('ethtool: problems calling ethtool or reading'
                              ' /sys/class on iface %s for attr %s' % \
                              (ifaceobj.name,attr))
        return running_attr


    def _query_running(self, ifaceobj, ifaceobj_getfunc=None):
        """
        _query_running looks at the speed and duplex from /sys/class
        and retreives autoneg from ethtool.  We do not report autoneg
        if speed is not available because this usually means the link is
        down and the autoneg value is not reliable when the link is down.
        """
        # do not bother showing swp ifaces that are not up for the speed
        # duplex and autoneg are not reliable.
        if not self.ipcmd.is_link_up(ifaceobj.name):
            return
        for attr in ['speed', 'duplex', 'autoneg']:
            default_val = policymanager.policymanager_api.get_iface_default(
                module_name='ethtool',
                ifname=ifaceobj.name,
                attr='link-%s'%attr)
            # do not continue if we have no defaults
            # this avoids ethtool calls on virtual interfaces
            if not default_val:
                continue
            running_attr = self.get_running_attr(attr, ifaceobj)
            # Only show the link attributes if they differ from defaults
            # to see the defaults, we should implement another flag (--with-defaults)
            if default_val == running_attr:
                continue
            if running_attr:
                ifaceobj.update_config('link-%s'%attr, running_attr)

        return

    _run_ops = {'pre-down' : _pre_down,
                'post-up' : _post_up,
                'query-checkcurr' : _query_check,
                'query-running' : _query_running }

    def get_ops(self):
        """ returns list of ops supported by this module """
        return self._run_ops.keys()

    def _init_command_handlers(self):
        if not self.ipcmd:
            self.ipcmd = iproute2()

    def run(self, ifaceobj, operation, query_ifaceobj=None, **extra_args):
        """ run ethtool configuration on the interface object passed as
            argument

        Args:
            **ifaceobj** (object): iface object

            **operation** (str): any of 'post-up', 'query-checkcurr',
                'query-running'
        Kwargs:
            **query_ifaceobj** (object): query check ifaceobject. This is only
                valid when op is 'query-checkcurr'. It is an object same as
                ifaceobj, but contains running attribute values and its config
                status. The modules can use it to return queried running state
                of interfaces. status is success if the running state is same
                as user required state in ifaceobj. error otherwise.
        """
        op_handler = self._run_ops.get(operation)
        if not op_handler:
            return
        self._init_command_handlers()

        if operation == 'query-checkcurr':
            op_handler(self, ifaceobj, query_ifaceobj)
        else:
            op_handler(self, ifaceobj)
