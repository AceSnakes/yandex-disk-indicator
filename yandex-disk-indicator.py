#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  Yandex.Disk indicator
appVer = '1.8.13'
#
#  Copyright 2014+ Sly_tom_cat <slytomcat@mail.ru>
#  based on grive-tools (C) Christiaan Diedericks (www.thefanclub.co.za)
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

import gi, os, sys, subprocess, pyinotify, fcntl, gettext, datetime, logging, re, argparse, locale
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
gi.require_version('AppIndicator3', '0.1')
from gi.repository import AppIndicator3 as appIndicator
gi.require_version('Notify', '0.7')
from gi.repository import Notify
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GdkPixbuf
from os.path import exists as pathExists, join as pathJoin
from shutil import copy as fileCopy
from webbrowser import open_new as openNewBrowser

#### Common utility functions and classes
def copyFile(src, dst):
  try:
    fileCopy (src, dst)
  except:
    logger.error("File Copy Error: from %s to %s" % (src, dst))

def deleteFile(dst):
  try:
    os.remove(dst)
  except:
    logger.error('File Deletion Error: %s' % dst)

def makedirs(dst):
  try:
    os.makedirs(dst, exist_ok=True)
  except:
    logger.error('Dirs creation Error: %s' % dst)

class CVal(object):             # Multivalue helper
  ''' Class to work with value that can be None, scalar item or list of items depending
      of number of elementary items added to it. '''

  def __init__(self, initialValue=None):
    self.set(initialValue)   # store initial value
    self.index = None

  def get(self):                  # It just returns the current value of cVal
    return self.val

  def set(self, value):           # Set internal value
    self.val = value
    if isinstance(self.val, list) and len(self.val) == 1:
      self.val = self.val[0]
    return self.val

  def add(self, item):            # Add item
    if isinstance(self.val, list):  # Is it third, fourth ... value?
      self.val.append(item)         # Just append new item to list
    elif self.val is None:          # Is it first item?
      self.val = item               # Just store item
    else:                           # It is the second item.
      self.val = [self.val, item]   # Convert scalar value to list of items.
    return self.val

  def remove(self, item):
    if isinstance(self.val, list):
      self.val.remove(item)
      if len(self.val) == 1:
        self.val = self.val[0]
    elif self.val is None:
      raise ValueError
    else:
      if self.val == item:
        self.val = None
      else:
        raise ValueError
    return self.val

  def __iter__(self):             # cVal iterator object initialization
    if isinstance(self.val, list):  # Is CVal a list?
      self.index = -1
    elif self.val is None:          # Is CVal not defined?
      self.index = None
    else:                           # CVal is scalar type.
      self.index = -2
    return self

  def __next__(self):             # cVal iterator support
    if self.index is None:            # Is CVal not defined?
      raise StopIteration             # Stop iterations
    self.index += 1
    if self.index >= 0:               # Is CVal a list?
      if self.index < len(self.val):  # Is there a next element in list?
        return self.val[self.index]
      else:                           # There is no more elements in list.
        self.index = None
        raise StopIteration           # Stop iterations
    else:                             # CVal has scalar type.
      self.index = None               # Remember that there is no more iterations possible
      return self.val

  def __str__(self):              # String representation of CVal
    return str(self.val)

  def __getitem__(self, index):   # Access to cVal items by index
    if isinstance(self.val, list):
      return self.val[index]          # It raises IndexError when index is out of range(len(cVal))
    elif self.val is None:
      raise IndexError                # None value cannot be received by any index
    elif not index:                   # cVal is scalar and index is 0?
      return self.val
    else:
      raise IndexError

  def __len__(self):              # Length of cVal
    if isinstance(self.val, list):
      return len(self.val)
    return 0 if self.val is None else 1

  def __contains__(self, item):   # 'in' opertor function
    if isinstance(self.val, list):
      return item in self.val
    elif self.val is None:
      return item is None
    else:
      return self.val == item

  def __bool__(self):
    return self.val is not None

class Config(dict):             # Configuration

  def __init__(self, fileName, load=True,
               bools=[['true', 'yes', 'y'], ['false', 'no', 'n']],
               boolval=['yes', 'no'], usequotes=True, delimiter='='):
    #super(Config, self).__init__(self)
    self.fileName = fileName
    self.bools = bools             # Values to detect boolean in self.load
    self.boolval = boolval         # Values to write boolean in self.save
    self.usequotes = usequotes     # Use quotes for keys and values in self.save
    self.delimiter = delimiter     # Use specified delimiter between key and value
    self.changed = False           # Change flag (for use outside of the class)
    if load:
      self.load()

  def decode(self, value):              # Convert string to value before store it
    #logger.debug("Decoded value: '%s'"%value)
    if value.lower() in self.bools[0]:
      value = True
    elif value.lower() in self.bools[1]:
      value = False
    return value

  def getValue(self, st):               # Parse value(s) from string after '='
    words = re.findall(r'("[^"]*")|([~/.\w-]+)', st)  # Get list of values
    words = [p[0]+p[1] for p in words]                # Join words variants
    # Check commas and not correct symbols that are not part of words
    # Substitute found words by '*' and split line by commas
    mask = re.sub((''.join(r'(?<=[\W])%s(?=[\W])|'%p for p in words))[:-1],
                   '*', ' %s ' % st).split(',')
    # Correctly masked value have to be just one '*' and possible surrounded by spaces
    # Number of '*' must be equal to number of words
    if sum([len(p.strip()) for p in mask]) == len(words):
      # Values are OK, store them
      res = CVal()
      for p in words:                                 # decode vales with removed quotes
        res.add(self.decode(p[1:-1] if p[0] == '"' else p))
      return res.get()
    else:
      return None                                     # Something wrong in values string

  def load(self, bools=[['true', 'yes', 'y'], ['false', 'no', 'n']], delimiter='='):
    """
    Reads config file to dictionary (OrderedDict).
    Config file should contain key=value rows.
    Key can be quoted or not.
    Value can be one item or list of comma-separated items. Each value item can be quoted or not.
    When value is a single item then it creates key:value item in dictionary
    When value is a list of items it creates key:[value, value,...] dictionary's item.
    """
    self.bools = bools
    self.delimiter = delimiter
    try:                              # Read configuration file into list of tuples ignoring blank
                                      # lines, lines without delimiter, and lines with comments.
      with open(self.fileName) as cf:
        res = [re.findall(r'^\s*(.+?)\s*%s\s*(.*)$' % self.delimiter, l)[0]
               for l in cf if l and self.delimiter in l and l.lstrip()[0] != '#']
      self.readSuccess = True
    except:
      logger.error('Config file read error: %s' % self.fileName)
      self.readSuccess = False
      return False
    for kv, vv in res:        # Parse each line
      # Check key
      key = re.findall(r'"([\w-]+)"$|^([\w-]+)$', kv)
      if not key:
        logger.warning('Wrong key in line \'%s %s %s\'' % (kv, self.delimiter, vv))
      else:                           # Key is OK
        key = key[0][0] + key[0][1]   # Join two possible keys variants (with and without quotes)
        if not vv.strip():
          logger.warning('No value specified in line \'%s %s %s\'' % (kv, self.delimiter, vv))
        else:                         # Value is not empty
          value = self.getValue(vv)   # Parse values
          if value is None:
            logger.warning('Wrong value(s) in line \'%s %s %s\'' % (kv, self.delimiter, vv))
          else:                       # Value is OK
            if key in self.keys():    # Check duble values
              logger.warning(('Double values for one key:\n%s = %s\nand\n%s = %s\n' +
                              'Last one is stored.') % (key,self[key],key,value))
            self[key] = value         # Store correct value
            logger.debug('Config value read as: %s = %s' % (key, str(value)))
    logger.info('Config read: %s' % self.fileName)
    return True

  def encode(self, val):                # Convert value to string before save it
    if isinstance(val, bool):       # Treat Boolean
      val = self.boolval[0] if val else self.boolval[1]
    if self.usequotes:
      val = '"' + val + '"'         # Put value within quotes
    return val

  def save(self, boolval=['yes', 'no'], usequotes=True, delimiter='='):
    self.usequotes = usequotes
    self.boolval = boolval
    self.delimiter = delimiter
    try:                                  # Read the file in buffer
      with open(self.fileName, 'rt') as cf:
        buf = cf.read()
    except:
      logger.warning('Config file access error, a new file (%s) will be created' % self.fileName)
      buf = ''
    while buf and buf[-1] == '\n':        # Remove ending blank lines
      buf = buf[:-1]
    buf += '\n'                           # Left only one
    for key, value in self.items():
      if value is None:
        res = ''                          # Remove 'key=value' from file if value is None
        logger.debug('Config value \'%s\' will be removed' % key)
      else:                               # Make a line with value
        res = ''.join([key, self.delimiter,
                       ''.join([self.encode(val) + ', ' for val in CVal(value)])[:-2] + '\n'])
        logger.debug('Config value to save: %s'%res[:-1])
      # Find line with key in file the buffer
      sRe = re.search(r'^[ \t]*["]?%s["]?[ \t]*%s.+\n' % (key, self.delimiter),
                      buf, flags=re.M)
      if sRe:                             # Value has been found
        buf = sRe.re.sub(res, buf)        # Replace it with new value
      elif res:                           # Value was not found and value is not empty
        buf += res                        # Add new value to end of file buffer
    try:
      with open(self.fileName, 'wt') as cf:
        cf.write(buf)                     # Write updated buffer to file
    except:
      logger.error('Config file write error: %s' % self.fileName)
      return False
    logger.info('Config written: %s' % self.fileName)
    self.changed = False
    return True

class Timer(object):            # Timer for triggering a function periodically
  ''' Timer class methods:
        __init__ - initialize the timer object with specified interval and handler. Start it
                   if start value is not False. par - is parameter for handler call.
        start    - Start timer. Optionally the new interval can be specified and if timer is
                   already running then the interval is updated (timer restarted with new interval).
        update   - Updates interval. If timer is running it is restarted with new interval. It it
                   is not running - then interval just stored.
        stop     - Stop running timer or do nothing if it is not running.
      Interface variables:
        active   - True when timer is currently running
  '''
  def __init__(self, interval, handler, par = None, start = True):
    self.interval = interval          # Timer interval (ms)
    self.handler = handler            # Handler function
    self.par = par                    # Parameter of handler function
    self.active = False               # Current activity status
    if start:
      self.start()                    # Start timer if required

  def start(self, interval = None):   # Start inactive timer or update if it is active
    if interval is None:
      interval = self.interval
    if not self.active:
      self.interval = interval
      if self.par is None:
        self.timer = GLib.timeout_add(interval, self.handler)
      else:
        self.timer = GLib.timeout_add(interval, self.handler, self.par)
      self.active = True
      #logger.debug('timer started %s %s' %(self.timer, interval))
    else:
      self.update(interval)

  def update(self, interval):         # Update interval (restart active, not start if inactive)
    if interval != self.interval:
      self.interval = interval
      if self.active:
        self.stop()
        self.start()

  def stop(self):                     # Stop active timer
    if self.active:
      #logger.debug('timer to stop %s' %(self.timer))
      GLib.source_remove(self.timer)
      self.active = False

class Notification(object):     # On-screen notification

  def __init__(self, app, mode):      # Initialize notification engine
    Notify.init(app)
    self.notifier = Notify.Notification()
    self.switch(mode)

  def send(self, title, message):     # Send notification
    pass                              # This method is redefined by switch method

  def switch(self, mode):             # Change show mode
    if mode:
      self.send = self._message       # Redefine send as real notification routine
    else:
      self.send = lambda t, m: None   # Redefine send as fake routine

  def _message(self, t, m):        # Show on-screen notification message
    global logo
    logger.debug('Message: %s | %s' % (t, m))
    try:
      self.notifier.update(t, m, logo)  # Update notification
      self.notifier.show()              # Display new notification
    except:
      logger.error('Message engine failure')

#### Main daemon/indicator classes
class YDDaemon(object):         # Yandex.Disk daemon interface
  '''
  This is the fully automated class that serves as daemon interface.
  Public methods:
  __init__ - Handles initialization of the object and as a part - auto-start daemon if it
             is required by configuration settings.
  getOuput - Provides daemon output (in user language if optional parameter workLang is
             False or missed)
  start    - Starts daemon if it is not started yet
  stop     - Stops running daemon
  exit     - Handles 'Stop on exit' facility according to daemon configuration settings.
  change   - Call back function for handling daemon status changes outside the class.
             It have to be redefined by UI update routine.
             The parameters of the call - status values dictionary (see vars description below)
             and the UpdateEvent object with with 4 boolean values:
              stat is True when status or progress has been changed,
              prog is True when synchronization progress has been changed,
              size is True when some of sizes has been changed,
              last is True when list of last synchronized has been changed,
              init is True when initial update event is raised.
  Class interface variables:
  config   - The daemon configuration dictionary (object of _DConfig(Config) class)
  vars     - status values dictionary with following keys:
              'status' - current daemon status
              'progress' - synchronization progress or ''
              'laststatus' - previous daemon status
              'total' - total Yandex disk spase
              'used' - currntly used spase
              'free' - available space
              'trash' - size of trash
              'lastitems' - list of last synchronized items or []
  ID       - the daemon identity string (empty in single daemon configuration)
  '''

  # Default daemon status values
  _dvals = {'status':'', 'progress':'', 'laststatus':'', 'total':'...',
           'used':'...', 'free':'...', 'trash':'...', 'lastitems':[]}

  class UpdateEvent(object):            # Changes control class

    def __init__(self):
      self.reset()

    def reset(self):      # Set initial values for object variables
      self.stat = False         # It become True when status or synchronisation progress changed
      self.prog = False         # It become True when synchronization progress changed
      self.size = False         # It become True when some sizes values changed
      self.last = False         # It become True when when list of last synchronized changed
      self.init = False         # It become True when initialization event raised

    def __bool__(self):   # Boolean representation of object
      return self.stat or self.prog or self.size or self.last or self.init

    def __str__(self):    # String representation of object
      str = (('stat, ' if self.stat else '') +
             ('prog, ' if self.prog else '') +
             ('size, ' if self.size else '') +
             ('last, ' if self.last else '') +
             ('init, ' if self.init else ''))
      return '{' + str[: (-2 if str else None)]+'}'

  class _Watcher(object):               # Daemon iNotify watcher
    '''
    iNotify watcher object for monitor of changes daemon internal log for the fastest
    reaction on status change.
    '''
    def __init__(self, handler, par=None):
      # Initialize iNotify watcher
      class _EH(pyinotify.ProcessEvent):           # Event handler class for iNotifier
        def process_IN_MODIFY(self, event):
          handler(par)
      self._watchMngr = pyinotify.WatchManager()   # Create watch manager
      # Create PyiNotifier
      self._iNotifier = pyinotify.Notifier(self._watchMngr, _EH(), timeout=0.5)
      # Timer will call iNotifier handler every .7 seconds (not started initially)
      self._timer = Timer(700, self._iNhandle, start=False)

    def _iNhandle(self):                 # iNotify working routine (called by timer)
      while self._iNotifier.check_events():
        self._iNotifier.read_events()
        self._iNotifier.process_events()
      return True

    def start(self, path):               # Activate iNotify watching
      # Prepare path
      self._path = pathJoin(path.replace('~', userHome), '.sync/cli.log')
      # Add watch
      self._watch = self._watchMngr.add_watch(self._path, pyinotify.IN_MODIFY, rec = False)
      # Activate timer
      self._timer.start()

    def stop(self):                      # Stop iNotify watching
      # Stop timer
      self._timer.stop()
      # Remove watch
      self._watchMngr.rm_watch(self._watch[self._path])

  class _DConfig(Config):               # Redefined class for daemon config

    def save(self):  # Update daemon config file
      # Make a copy of Self as super class
      fileConfig = Config(self.fileName, load=False)
      fileConfig.update(self)
      # Convert values representation
      ro = fileConfig.get('read-only', False)
      fileConfig['read-only'] = '' if ro else None
      fileConfig['overwrite'] = '' if fileConfig.get('overwrite', False) and ro else None
      exList = fileConfig.get('exclude-dirs', None)
      if exList:
        fileConfig['exclude-dirs'] = ''.join([i + ',' for i in CVal(exList)])[:-1]
      fileConfig.save()
      self.changed=False

    def load(self):  # Get daemon config from its config file
      if super(YDDaemon._DConfig, self).load():             # Load config from file
        # Convert values representations
        self['read-only'] = (self.get('read-only', False) == '')
        self['overwrite'] = (self.get('overwrite', False) == '')
        self.setdefault('startonstartofindicator', True)    # New value to start daemon individually
        self.setdefault('stoponexitfromindicator', False)   # New value to stop daemon individually
        exDirs = self.setdefault('exclude-dirs', None)
        if isinstance(exDirs, str):
          # Additional parsing required when quoted value like "dir,dir,dir" is specified.
          # When the value specified without quotes it will be already list like [dir, dir, dir].
          self['exclude-dirs'] = self.getValue(exDirs)
        return True
      else:
        return False

  def __init__(self, cfgFile, ID):      # Check that daemon installed and configured
    '''
    cfgFile  - full path to config file
    ID       - identity string '#<n> ' in multi-instance environment or
               '' in single instance environment'''
    self.ID = ID                                      # Remember daemon identity
    if not pathExists('/usr/bin/yandex-disk'):
      self._ErrorDialog('NOTINSTALLED')
      appExit('Daemon is not installed')
    # Try to read Yandex.Disk configuration file and make sure that it is correctly configured
    self.config = self._DConfig(cfgFile, load=False)
    while not (self.config.load() and
               pathExists(self.config.get('dir', '')) and
               pathExists(self.config.get('auth', ''))):
      if self._errorDialog('NOCONFIG') != 0:
        if ID:
          self.config['dir'] = ''
          # Exit from loop in multi-instance configuration
          break
        else:
          appExit('Daemon is not configured')
    # Initialize watching staff
    self._wTimer = Timer(2000, self._eventHandler, par=False, start=True)
    self._tCnt = 0
    self._iNtfyWatcher = self._Watcher(self._eventHandler, par=True)
    self.update = YDDaemon.UpdateEvent()              # Initialize changes control object
    self.vals = YDDaemon._dvals.copy()                # Load default daemon status values
    # Check that daemon is running
    out = self.getOutput()
    if out:                                           # Is daemon running?
      self._parseOutput(out)                          # Update status values
      self.vals['laststatus'] = self.vals['status']   # Set unknown last status as current status
      self.update.init = True                         # Remember that it is initial change event
      self.change(self.vals, self.update)             # Manually raise initial change event
      self._iNtfyWatcher.start(self.config['dir'])    # Activate iNotify watcher
    else:                                             # Daemon is not running
      started = False
      if self.config.get('startonstartofindicator', True):
        started = not self.start()                    # Start daemon if it is required
      if not started:
        self.update.init = True                       # Remember that it is initial change event
        self.vals['status'] = 'none'                  # Set current status as 'none'
        self.vals['laststatus'] = 'none'              # Set unknown last status also as 'none'
        self.change(self.vals, self.update)           # Manually raise initial change event

  def _eventHandler(self, iNtf):        # Daemon event handler
    '''
    Handle iNotify and and Timer based events.
    After receiving and parsing the daemon output it raises outside change event if daemon changes
    at least one of its status values.
    It can be called by timer (when byNotifier=False) or by iNonifier
    (when byNotifier=True)'''

    # Parse fresh daemon output. Parsing returns true when something changed
    if self._parseOutput(self.getOutput()):
      self.change(self.vals, self.update)     # Raise outside update event
    logger.debug('Raw event ' + self.ID + ('iNtfy ' if iNtf else 'Timer ') +
                 self.vals['laststatus'] + ' -> ' + self.vals['status'])
    # --- Handle timer delays ---
    if iNtf:                                  # True means that it is called by iNonifier
      self._wTimer.update(2000)               # Set timer interval to 2 sec.
      self._tCnt = 0                          # Reset counter as it was triggered not by timer
    else:                                     # It called by timer
      if self.vals['status'] != 'busy':       # In 'busy' keep update interval (2 sec.)
        if self._tCnt < 9:                    # Increase interval up to 10 sec (2 + 8)
          self._wTimer.update((2 + self._tCnt)*1000)
          self._tCnt += 1                     # Increase counter to increase delay next activation.
    return True                               # True is required to continue activations by timer.

  def change(self, vals, update):       # Redefined update handler
    logger.debug('Update event: %s \nValues : %s' % (str(update), str(vals)))

  def getOutput(self, userLang=False):  # Get result of 'yandex-disk status'
    cmd = ['yandex-disk','-c', self.config.fileName, 'status']
    if not userLang:      # Change locale settings when it required
      cmd = ['env', '-i', "LANG='en_US.UTF8'"] + cmd
    try:
      output = subprocess.check_output(cmd, universal_newlines=True)
    except:
      output = ''         # daemon is not running or bad
    #logger.debug('output = %s' % output)

    return output

  def _parseOutput(self, out):          # Parse the daemon output
    '''
    It parses the daemon output and check that something changed from last daemon status.
    The self.vals dictionary is updated with new daemon statuses and self.update set represents
    the changes in self.vals. It returns True is something changed

    Daemon status is converted form daemon raw statuses into internal representation.
    Internal status can be on of the following: 'busy', 'idle', 'paused', 'none', 'no_net', 'error'.
    Conversion is done by following rules:
     - empty status (daemon is not running) converted to 'none'
     - statuses 'busy', 'idle', 'paused' are passed 'as is'
     - 'index' is ignored (previous status is kept)
     - 'no internet access' converted to 'no_net'
     - 'error' covers all other errors, except 'no internet access'
    '''
    self.update.reset()                     # Reset updates object
    # Split output on two parts: list of named values and file list
    output = out.split('Last synchronized items:')
    if len(output) == 2:
      files = output[1]
    else:
      files = ''
    output = output[0].splitlines()
    # Make a dictionary from named values (use only lines containing ':')
    res = dict([re.findall(r'\s*(.+):\s*(.*)', l)[0] for l in output if ':' in l])
    # Parse named status values
    for srch, key in (('Synchronization core status', 'status'), ('Sync progress', 'progress'),
                      ('Total', 'total'), ('Used', 'used'), ('Available', 'free'),
                      ('Trash size', 'trash')):
      val = res.get(srch, '')
      if key == 'status':                   # Convert status to internal representation
        #logger.debug('Raw status : \'%s\', previous status: %s'%(val, self.vals['status']))
        # Store previous status
        self.vals['laststatus'] = self.vals['status']
        # Convert daemon raw status to internal representation
        val = (# Convert '' into 'none' status
               'none' if not val else
               # Ignore index status
               self.vals['laststatus'] if val == 'index' else
               # Rename long error status
               'no_net' if val == 'no internet access' else
               # pass 'busy', 'idle' and 'paused' statuses 'as is'
               val if val in ['busy', 'idle', 'paused'] else
               # Status 'error' covers 'error', 'failed to connect to daemon process' and other.
               'error')
      elif key != 'progress' and not val:   # 'progress' can be '' the rest - can't
        val = '...'                         # Make default filling for empty values
      # Check value change and store changed
      if self.vals[key] != val:             # Check change of value
        self.vals[key] = val                # Store new value
        if key == 'status':
          self.update.stat = True           # Remember that status changed
        elif key == 'progress':
          self.update.prog = True           # Remember that progress cahnged
        else:
          self.update.size = True           # Remember that something changed in sizes values
    # Parse last synchronized items
    buf = re.findall(r".*: '(.*)'\n", files)
    # Check if file list has been changed
    if self.vals['lastitems'] != buf:
      self.vals['lastitems'] = buf          # Store the new file list
      self.update.last = True               # Remember that it is changed
    return bool(self.update)

  def _errorDialog(self, err):          # Show error messages according to the error
    global logo
    logger.error('Daemon initialization failed: %s', err)
    if err == 'NOCONFIG' or err == 'CANTSTART':
      dialog = Gtk.MessageDialog(None, 0, Gtk.MessageType.INFO, Gtk.ButtonsType.OK_CANCEL,
                                 _('Yandex.Disk Indicator: daemon start failed'))
      if err == 'NOCONFIG':
        dialog.format_secondary_text(_('Yandex.Disk daemon failed to start because it is not' +
         ' configured properly\n  To configure it up: press OK button.\n  Press Cancel to exit.'))
      else:
        dialog.format_secondary_text(_('Yandex.Disk daemon failed to start.' +
         '\n  Press OK to continue without started daemon or Cancel to exit.'))
    else:
      dialog = Gtk.MessageDialog(None, 0, Gtk.MessageType.INFO, Gtk.ButtonsType.OK,
                                 _('Yandex.Disk Indicator: daemon start failed'))
      if err == 'NONET':
        dialog.format_secondary_text(_('Yandex.Disk daemon failed to start due to network' +
          ' connection issue. \n  Check the Internet connection and try to start daemon again.'))
      elif err == 'NOTINSTALLED':
        dialog.format_secondary_text(_('Yandex.Disk utility is not installed.\n ' +
          'Visit www.yandex.ru, download and install Yandex.Disk daemon.'))
      else:
        dialog.format_secondary_text(_('Yandex.Disk daemon failed to start due to some ' +
                                       'unrecognised error.'))
    dialog.set_default_size(400, 250)
    dialog.set_icon(GdkPixbuf.Pixbuf.new_from_file(logo))
    response = dialog.run()
    dialog.destroy()
    if err == 'NOCONFIG' and response == Gtk.ResponseType.OK:  # Launch Set-up utility
      logger.debug('starting configuration utility: %s' % pathJoin(installDir, 'ya-setup'))
      retCode = subprocess.call([pathJoin(installDir,'ya-setup'), self.config.fileName])
    elif err == 'CANTSTART' and response == Gtk.ResponseType.OK:
      retCode = 0
    else:
      retCode = 0 if err == 'NONET' else 1
    dialog.destroy()
    return retCode              # 0 when error is not critical or fixed (daemon has been configured)

  def start(self):                      # Execute 'yandex-disk start'
    '''
    Execute 'yandex-disk start' and return '' if success or error message if not
    ... but sometime it starts successfully with error message
    Additionally it starts iNotify monitoring in case of success start
    '''
    err = ''
    while True:
      try:                                          # Try to start
        msg = subprocess.check_output(['yandex-disk', '-c', self.config.fileName, 'start'],
                                      universal_newlines=True)
        logger.info('Start success, message: %s' % msg)
        err =  ''
      except subprocess.CalledProcessError as e:
        logger.error('Daemon start failed:%s' % e.output)
        if e.output == '':                          # Probably 'os: no file'
          return 'NOTINSTALLED'
        err = ('NONET' if 'Proxy' in e.output else
               'BADDAEMON' if 'daemon' in e.output else
               'NOCONFIG' if "'dir'" in e.output or 'OAuth' in e.output else
               err)
      # Handle the starting error
      if err != '' and self._errorDialog(err) == 0:
        self.config.load()                          # Reload created configuration file & try again
      else:
        break
    if err == '':
      self.vals = YDDaemon._dvals.copy()            # Initialise default values
      self._parseOutput(self.getOutput())           # Parse fresh daemon output
      self.update.init = True                       # Remember that it is initial change event
      self.vals['status'] = 'paused'                # Set current status to avoid index status
      self.vals['laststatus'] = 'none'              # Set well known previous status
      self.change(self.vals, self.update)           # Manually raise initial change event
      self._iNtfyWatcher.start(self.config['dir'])  # Activate watcher with self.handler
    return err

  def stop(self):                       # Execute 'yandex-disk stop'
    try:
      msg = subprocess.check_output(['yandex-disk', '-c', self.config.fileName, 'stop'],
                                    universal_newlines=True)
    except:
      msg = ''
    if msg:
      self._iNtfyWatcher.stop()
      self._eventHandler(True)          # Manually call evetHanler to raise change event
      return True
    else:
      return False

  def exit(self):                       # Handle daemon/indicator closing
    # Stop yandex-disk daemon if it is required by its configuration
    if self.vals['status'] != 'none' and self.config.get('stoponexitfromindicator', False):
      self.stop()
      logger.info('Demon %sstopped'%self.ID)

class Indicator(YDDaemon):      # Yandex.Disk appIndicator

  def __init__(self, path, ID):
    indicatorName = "yandex-disk-%s"%ID[1:-1]
    # Create indicator notification engine
    self.notify = Notification(indicatorName, config['notifications'])
    # Setup icons theme
    self.setIconTheme(config['theme'])
    # Create timer object for icon animation support (don't start it here)
    self.timer = Timer(777, self._iconAnimation, start=False)
    # Create App Indicator
    self.ind = appIndicator.Indicator.new(indicatorName, self.icon['paused'],
                                          appIndicator.IndicatorCategory.APPLICATION_STATUS)
    self.ind.set_status(appIndicator.IndicatorStatus.ACTIVE)
    self.menu = self.Menu(self, ID)               # Create menu for daemon
    self.ind.set_menu(self.menu)                  # Attach menu to indicator
    # Initialize Yandex.Disk daemon connection object
    super(Indicator, self).__init__(path, ID)

  def change(self, vals, update):   # Redefinition of daemon class call-back function
    '''
    It handles daemon status changes by updating icon, creating messages and also update
    status information in menu (status, sizes and list of last synchronized items).
    It is called when daemon detects any change of its status.
    '''
    logger.info(self.ID + 'Change event: %s'%str(update))
    # Update information in menu
    self.menu.update(vals, update, self.config['dir'])
    # Handle daemon status change by icon change
    if update.stat or update.init:
      self.updateIcon()                   # Update icon
    # Create notifications for status change events
    if update.stat:
      if vals['laststatus'] == 'none':    # Daemon has been started
        self.notify.send(_('Yandex.Disk ')+self.ID, _('Yandex.Disk daemon has been started'))
      if vals['status'] == 'busy':        # Just entered into 'busy'
        self.notify.send(_('Yandex.Disk ')+self.ID, _('Synchronization started'))
      elif vals['status'] == 'idle':      # Just entered into 'idle'
        if vals['laststatus'] == 'busy':  # ...from 'busy' status
          self.notify.send(_('Yandex.Disk ')+self.ID, _('Synchronization has been completed'))
      elif vals['status'] =='paused':     # Just entered into 'paused'
        if vals['laststatus'] != 'none':  # ...not from 'none' status
          self.notify.send(_('Yandex.Disk ')+self.ID, _('Synchronization has been paused'))
      elif vals['status'] == 'none':      # Just entered into 'none' from some another status
          self.notify.send(_('Yandex.Disk ')+self.ID, _('Yandex.Disk daemon has been stopped'))
      else:                               # status is 'error' or 'no-net'
        self.notify.send(_('Yandex.Disk ')+self.ID, _('Synchronization ERROR'))

  def setIconTheme(self, theme):    # Determine paths to icons according to current theme
    global installDir, configPath
    theme = 'light' if theme else 'dark'
    # Determine theme from application configuration settings
    defaultPath = pathJoin(installDir, 'icons', theme)
    userPath = pathJoin(configPath, 'icons', theme)
    # Set appropriate paths to all status icons
    self.icon = dict()
    for status in ['idle', 'error', 'paused', 'none', 'no_net', 'busy']:
      name = ('yd-ind-pause.png' if status in {'paused', 'none', 'no_net'} else
              'yd-busy1.png' if status == 'busy' else
              'yd-ind-'+status+'.png')
      userIcon = pathJoin(userPath, name)
      self.icon[status] = userIcon if pathExists(userIcon) else pathJoin(defaultPath, name)
      # userIcon corresponds to busy icon on exit from this loop
    # Set theme paths according to existence of first busy icon
    self.themePath = userPath if pathExists(userIcon) else defaultPath

  def updateIcon(self):             # Change indicator icon according to just changed daemon status
    # Set icon according to the current status
    self.ind.set_icon(self.icon[self.vals['status']])
    # Handle animation
    if self.vals['status'] == 'busy':   # Just entered into 'busy' status
      self._seqNum = 2                  # Next busy icon number for animation
      self.timer.start()                # Start animation timer
    elif self.timer.active:
      self.timer.stop()                 # Stop animation timer when status is not busy

  def _iconAnimation(self):         # Changes busy icon by loop (triggered by self.timer)
    # Set next animation icon
    self.ind.set_icon(pathJoin(self.themePath, 'yd-busy' + str(self._seqNum) + '.png'))
    # Calculate next icon number
    self._seqNum = self._seqNum % 5 + 1   # 5 icon numbers in loop (1-2-3-4-5-1-2-3...)
    return True                           # True required to continue triggering by timer

  class Menu(Gtk.Menu):             # Indicator menu

    def __init__(self, daemon, ID):
      self.daemon = daemon                      # Store reference to daemon object for future usage
      Gtk.Menu.__init__(self)                   # Create menu
      self.ID = ID
      if self.ID:                               # Add addition field in multidaemon mode
        self.yddir = Gtk.MenuItem('');  self.yddir.set_sensitive(False);   self.append(self.yddir)
      self.status = Gtk.MenuItem();     self.status.connect("activate", self.showOutput)
      self.append(self.status)
      self.used = Gtk.MenuItem();       self.used.set_sensitive(False)
      self.append(self.used)
      self.free = Gtk.MenuItem();       self.free.set_sensitive(False)
      self.append(self.free)
      self.last = Gtk.MenuItem(_('Last synchronized items'))
      self.lastItems = Gtk.Menu()               # Sub-menu: list of last synchronized files/folders
      self.last.set_submenu(self.lastItems)     # Add submenu (empty at the start)
      self.append(self.last)
      self.append(Gtk.SeparatorMenuItem.new())  # -----separator--------
      self.daemon_start = Gtk.MenuItem(_('Start Yandex.Disk daemon'))
      self.daemon_start.connect("activate", self.startDaemon)
      self.append(self.daemon_start)
      self.daemon_stop = Gtk.MenuItem(_('Stop Yandex.Disk daemon'))
      self.daemon_stop.connect("activate", self.stopDaemon);
      self.append(self.daemon_stop)
      self.open_folder = Gtk.MenuItem(_('Open Yandex.Disk Folder'))
      self.append(self.open_folder)
      open_web = Gtk.MenuItem(_('Open Yandex.Disk on the web'))
      open_web.connect("activate", self.openInBrowser, _('https://disk.yandex.com'))
      self.append(open_web)
      self.append(Gtk.SeparatorMenuItem.new())  # -----separator--------
      self.preferences = Gtk.MenuItem(_('Preferences'))
      self.preferences.connect("activate", Preferences)
      self.append(self.preferences)
      open_help = Gtk.MenuItem(_('Help'))
      m_help = Gtk.Menu()
      help1 = Gtk.MenuItem(_('Yandex.Disk daemon'))
      help1.connect("activate", self.openInBrowser, _('https://yandex.com/support/disk/'))
      m_help.append(help1)
      help2 = Gtk.MenuItem(_('Yandex.Disk Indicator'))
      help2.connect("activate", self.openInBrowser,
                    _('https://github.com/slytomcat/yandex-disk-indicator/wiki'))
      m_help.append(help2)
      open_help.set_submenu(m_help)
      self.append(open_help)
      self.about = Gtk.MenuItem(_('About'));    self.about.connect("activate", self.openAbout)
      self.append(self.about)
      self.append(Gtk.SeparatorMenuItem.new())  # -----separator--------
      close = Gtk.MenuItem(_('Quit'))
      close.connect("activate", self.close)
      self.append(close)
      self.show_all()
      # Define user readable statuses dictionary
      self.YD_STATUS = {'idle': _('Synchronized'), 'busy': _('Sync.: '), 'none': _('Not started'),
                        'paused': _('Paused'), 'no_net': _('Not connected'), 'error':_('Error') }

    def update(self, vals, update, yddir):  # Update information in menu
      # Update status data
      if update.stat or update.prog or update.init:
        logger.debug(vals['status']+self.YD_STATUS[vals['status']])
        self.status.set_label(_('Status: ') + self.YD_STATUS[vals['status']] +
                              (vals['progress'] if vals['status'] == 'busy' else ''))
      # Update sizes data
      if update.size or update.init:
        self.used.set_label(_('Used: ') + vals['used'] + '/' + vals['total'])
        self.free.set_label(_('Free: ') + vals['free'] + _(', trash: ') + vals['trash'])
      # Update last synchronized sub-menu when daemon is running
      if (update.last or update.init) and vals['status'] != 'none':
        for widget in self.lastItems.get_children():  # Clear last synchronized sub-menu
          self.lastItems.remove(widget)
        for filePath in vals['lastitems']:            # Create new sub-menu items
          # Create menu label as file path (shorten it down to 50 symbols when path length > 50
          # symbols), with replaced underscore (to disable menu acceleration feature of GTK menu).
          widget = Gtk.MenuItem.new_with_label(
                       (filePath[: 20] + '...' + filePath[-27: ] if len(filePath) > 50 else
                        filePath).replace('_', u'\u02CD'))
          filePath = pathJoin(yddir, filePath)        # Make full path to file
          if pathExists(filePath):
            widget.set_sensitive(True)                # If it exists then it can be opened
            widget.connect("activate", self.openPath, filePath)
          else:
            widget.set_sensitive(False)               # Don't allow to open non-existing path
          self.lastItems.append(widget)
          widget.show()
        if not vals['lastitems']:                     # No items in list?
          self.last.set_sensitive(False)
        else:                                         # There are some items in list
          self.last.set_sensitive(True)
        logger.debug("Sub-menu 'Last synchronized' has been updated")
      # Update 'static' elements of menu
      if 'none' in (vals['status'], vals['laststatus']) or update.init:
        started = vals['status'] != 'none'
        self.status.set_sensitive(started)
        self.daemon_stop.set_sensitive(started)
        self.daemon_start.set_sensitive(not started)
        self.last.set_sensitive(started)
        if self.ID:                                   # Set daemon identity row in multidaemon mode
          folder = (yddir.replace('_', u'\u02CD') if yddir else '< NOT CONFIGURED >')
          self.yddir.set_label(self.ID + _('  Folder: ') + folder)
        if yddir:                                     # Activate Open YDfolder if daemon configured
          self.open_folder.connect("activate", self.openPath, yddir)
          self.open_folder.set_sensitive(True)
        else:
          self.open_folder.set_sensitive(False)

    def openAbout(self, widget):            # Show About window
      global logo, indicators
      for i in indicators:
        i.menu.about.set_sensitive(False)           # Disable menu item
      aboutWindow = Gtk.AboutDialog()
      pic = GdkPixbuf.Pixbuf.new_from_file(logo)
      aboutWindow.set_logo(pic);   aboutWindow.set_icon(pic)
      aboutWindow.set_program_name(_('Yandex.Disk indicator'))
      aboutWindow.set_version(_('Version ') + appVer)
      aboutWindow.set_copyright('Copyright ' + u'\u00a9' + ' 2013-' +
                                datetime.datetime.now().strftime("%Y") + '\nSly_tom_cat')
      aboutWindow.set_license(
        'This program is free software: you can redistribute it and/or \n' +
        'modify it under the terms of the GNU General Public License as \n' +
        'published by the Free Software Foundation, either version 3 of \n' +
        'the License, or (at your option) any later version.\n\n' +
        'This program is distributed in the hope that it will be useful, \n' +
        'but WITHOUT ANY WARRANTY; without even the implied warranty \n' +
        'of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. \n' +
        'See the GNU General Public License for more details.\n\n' +
        'You should have received a copy of the GNU General Public License \n' +
        'along with this program.  If not, see http://www.gnu.org/licenses')
      aboutWindow.set_authors([_('Sly_tom_cat (slytomcat@mail.ru) '),
        _('ya-setup utility author: Snow Dimon (snowdimon.ru)'),
        _('\nSpecial thanks to:'),
        _(' - Christiaan Diedericks (www.thefanclub.co.za) - autor of Grive tools(used as example)'),
        _(' - ryukusu_luminarius (my-faios@ya.ru) - icons designer'),
        _(' - metallcorn (metallcorn@jabber.ru) - icons designer'),
        _(' - Chibiko (zenogears@jabber.ru) - deb package creation assistance'),
        _(' - RingOV (ringov@mail.ru) - localization assistance'),
        _(' - GreekLUG team (https://launchpad.net/~greeklug) - Greek translation'),
        _(' - Peyu Yovev (spacy00001@gmail.com) - Bulgarian translation'),
        _(' - Eldar Fahreev (fahreeve@yandex.ru) - FM actions for Pantheon-files'),
        _(' - Ace Of Snakes (aceofsnakesmain@gmail.com) - optimization of FM actions for Dolphin'),
        _(' - Ivan Burmin (https://github.com/Zirrald) - ya-setup multilingual support'),
        _(' - And to all other people who contributed to this project through'),
        _('   the Ubuntu.ru forum http://forum.ubuntu.ru/index.php?topic=241992 and'),
        _('   via github.com https://github.com/slytomcat/yandex-disk-indicator') ])
      aboutWindow.run()
      aboutWindow.destroy()
      for i in indicators:
        i.menu.about.set_sensitive(True)            # Enable menu item

    def showOutput(self, widget):           # Display daemon output in dialogue window
      global lang
      widget.set_sensitive(False)                         # Disable menu item
      statusWindow = Gtk.Dialog(_('Yandex.Disk daemon output message'))
      statusWindow.set_icon(GdkPixbuf.Pixbuf.new_from_file(logo))
      statusWindow.set_border_width(6)
      statusWindow.add_button(_('Close'), Gtk.ResponseType.CLOSE)
      textBox = Gtk.TextView()                            # Create text-box to display daemon output
      # Set output buffer with daemon output in user language
      textBox.get_buffer().set_text(self.daemon.getOutput(True))
      textBox.set_editable(False)
      statusWindow.get_content_area().add(textBox)        # Put it inside the dialogue content area
      statusWindow.show_all();  statusWindow.run();   statusWindow.destroy()
      widget.set_sensitive(True)                          # Enable menu item

    def openInBrowser(self, widget, url):   # Open URL
      openNewBrowser(url)

    def startDaemon(self, widget):          # Start daemon
      self.daemon.start()

    def stopDaemon(self, widget):           # Stop daemon
      self.daemon.stop()

    def openPath(self, widget, path):       # Open path
      logger.info('Opening %s' % path)
      if pathExists(path):
        try:
          os.startfile(path)
        except:
          subprocess.call(['xdg-open', path])

    def close(self, widget):                # Quit from indicator
      appExit()

#### Application functions and classes
class Preferences(Gtk.Dialog):  # Preferences window of application and daemons

  class excludeDirsList(Gtk.Dialog):                                      # Excluded list dialogue

    def __init__(self, widget, parent, dcofig):   # show current list
      self.dconfig = dcofig
      self.parent = parent
      Gtk.Dialog.__init__(self, title=_('Folders that are excluded from synchronization'),
                          parent=parent, flags=1)
      self.set_icon(GdkPixbuf.Pixbuf.new_from_file(logo))
      self.set_border_width(6)
      self.add_button(_('Add catalogue'),
                      Gtk.ResponseType.APPLY).connect("clicked", self.addFolder, self)
      self.add_button(_('Remove selected'),
                      Gtk.ResponseType.REJECT).connect("clicked", self.deleteSelected)
      self.add_button(_('Close'),
                      Gtk.ResponseType.CLOSE).connect("clicked", self.exitFromDialog)
      self.excludeList = Gtk.ListStore(bool , str)
      view = Gtk.TreeView(model=self.excludeList)
      render = Gtk.CellRendererToggle()
      render.connect("toggled", self.lineToggled)
      view.append_column(Gtk.TreeViewColumn(" ", render, active=0))
      view.append_column(Gtk.TreeViewColumn(_('Path'), Gtk.CellRendererText(), text=1))
      self.get_content_area().add(view)
      # Populate list with paths from "exclude-dirs" property of daemon configuration
      for val in CVal(self.dconfig.get('exclude-dirs', None)):
        self.excludeList.append([False, val])
      self.show_all()

    def exitFromDialog(self, widget):     # Save list from dialogue to "exclude-dirs" property
      if self.dconfig.changed:
        exList = CVal()                                     # Store path value from dialogue rows
        listIter = self.excludeList.get_iter_first()
        while listIter != None:
          exList.add(self.excludeList.get(listIter, 1)[0])
          listIter = self.excludeList.iter_next(listIter)
        self.dconfig['exclude-dirs'] = exList.get()         # Save collected value
      self.destroy()                                        # Close dialogue

    def lineToggled(self, widget, path):  # Line click handler, it switch row selection
      self.excludeList[path][0] = not self.excludeList[path][0]

    def deleteSelected(self, widget):     # Remove selected rows from list
      listIiter = self.excludeList.get_iter_first()
      while listIiter != None and self.excludeList.iter_is_valid(listIiter):
        if self.excludeList.get(listIiter, 0)[0]:
          self.excludeList.remove(listIiter)
          self.dconfig.changed = True
        else:
          listIiter = self.excludeList.iter_next(listIiter)

    def addFolder(self, widget, parent):  # Add new path to list via FileChooserDialog
      dialog = Gtk.FileChooserDialog(_('Select catalogue to add to list'), parent,
                                   Gtk.FileChooserAction.SELECT_FOLDER,
                                   (_('Close'), Gtk.ResponseType.CANCEL,
                                    _('Select'), Gtk.ResponseType.ACCEPT))
      dialog.set_default_response(Gtk.ResponseType.CANCEL)
      rootDir = self.dconfig['dir']
      dialog.set_current_folder(rootDir)
      if dialog.run() == Gtk.ResponseType.ACCEPT:
        self.excludeList.append([False, os.path.relpath(dialog.get_filename(), start=rootDir)])
        self.dconfig.changed = True
      dialog.destroy()

  def __init__(self, widget):
    global config, indicators
    # Preferences Window routine
    for i in indicators:
      i.menu.preferences.set_sensitive(False)   # Disable menu items to avoid multi-dialogs creation
    # Create Preferences window
    Gtk.Dialog.__init__(self, _('Yandex.Disk-indicator and Yandex.Disks preferences'), flags=1)
    self.set_icon(GdkPixbuf.Pixbuf.new_from_file(logo))
    self.set_border_width(6)
    self.add_button(_('Close'), Gtk.ResponseType.CLOSE)
    pref_notebook = Gtk.Notebook()              # Create notebook for indicator and daemon options
    self.get_content_area().add(pref_notebook)  # Put it inside the dialogue content area
    # --- Indicator preferences tab ---
    preferencesBox = Gtk.VBox(spacing=5)
    cb = []
    for key, msg in [('autostart', _('Start Yandex.Disk indicator when you start your computer')),
                     ('notifications', _('Show on-screen notifications')),
                     ('theme', _('Prefer light icon theme')),
                     ('fmextensions', _('Activate file manager extensions'))]:
      cb.append(Gtk.CheckButton(msg))
      cb[-1].set_active(config[key])
      cb[-1].connect("toggled", self.onButtonToggled, cb[-1], key)
      preferencesBox.add(cb[-1])
    # --- End of Indicator preferences tab --- add it to notebook
    pref_notebook.append_page(preferencesBox, Gtk.Label(_('Indicator settings')))
    # Add daemos tabs
    for i in indicators:
      # --- Daemon start options tab ---
      optionsBox = Gtk.VBox(spacing=5)
      key = 'startonstartofindicator'           # Start daemon on indicator start
      cbStOnStart = Gtk.CheckButton(_('Start Yandex.Disk daemon %swhen indicator is starting')%i.ID)
      cbStOnStart.set_tooltip_text(_("When daemon was not started before."))
      cbStOnStart.set_active(i.config[key])
      cbStOnStart.connect("toggled", self.onButtonToggled, cbStOnStart, key, i.config)
      optionsBox.add(cbStOnStart)
      key = 'stoponexitfromindicator'           # Stop daemon on exit
      cbStoOnExit = Gtk.CheckButton(_('Stop Yandex.Disk daemon %son closing of indicator')%i.ID)
      cbStoOnExit.set_active(i.config[key])
      cbStoOnExit.connect("toggled", self.onButtonToggled, cbStoOnExit, key, i.config)
      optionsBox.add(cbStoOnExit)
      frame = Gtk.Frame()
      frame.set_label(_("NOTE! You have to reload daemon %sto activate following settings")%i.ID)
      frame.set_border_width(6)
      optionsBox.add(frame)
      framedBox = Gtk.VBox(homogeneous=True, spacing=5)
      frame.add(framedBox)
      key = 'read-only'                         # Option Read-Only    # daemon config
      cbRO = Gtk.CheckButton(_('Read-Only: Do not upload locally changed files to Yandex.Disk'))
      cbRO.set_tooltip_text(_("Locally changed files will be renamed if a newer version of this " +
                              "file appear in Yandex.Disk."))
      cbRO.set_active(i.config[key])
      key = 'overwrite'                         # Option Overwrite    # daemon config
      overwrite = Gtk.CheckButton(_('Overwrite locally changed files by files' +
                                         ' from Yandex.Disk (in read-only mode)'))
      overwrite.set_tooltip_text(
        _("Locally changed files will be overwritten if a newer version of this file appear " +
          "in Yandex.Disk."))
      overwrite.set_active(i.config[key])
      overwrite.set_sensitive(i.config['read-only'])
      cbRO.connect("toggled", self.onButtonToggled, cbRO, 'read-only', i.config, overwrite)
      framedBox.add(cbRO)
      overwrite.connect("toggled", self.onButtonToggled, overwrite, key, i.config)
      framedBox.add(overwrite)
      # Excude folders list
      exListButton = Gtk.Button(_('Excluded folders List'))
      exListButton.set_tooltip_text(_("Folders in the list will not be synchronized."))
      exListButton.connect("clicked", self.excludeDirsList, self, i.config)
      framedBox.add(exListButton)
      # --- End of Daemon start options tab --- add it to notebook
      pref_notebook.append_page(optionsBox, Gtk.Label(_('Daemon %soptions')%i.ID))
    self.show_all()
    self.run()
    if config.changed:
      config.save()                             # Save app config
    for i in indicators:
      if i.config.changed:
        i.config.save()                  # Save daemon options in config file
      i.menu.preferences.set_sensitive(True)    # Enable menu items
    self.destroy()

  def onButtonToggled(self, widget, button, key, dconfig=None, ow=None):  # Handle clicks
    toggleState = button.get_active()
    logger.debug('Togged: %s  val: %s' % (key, str(toggleState)))
    # Update configurations
    if key in ['read-only', 'overwrite', 'startonstartofindicator', 'stoponexitfromindicator']:
      dconfig[key] = toggleState                # Update daemon config
      dconfig.changed = True
    else:
      config.changed = True                     # Update application config
      config[key] = toggleState
    if key == 'theme':
        for i in indicators:                    # Update all indicators' icons
          i.setIconTheme(toggleState)           # Update icon theme
          i.updateIcon()                        # Update current icon
    elif key == 'notifications':
      notify.switch(toggleState)                # Update application notification engine
      for i in indicators:                      # Update all notification engines
        i.notify.switch(toggleState)
    elif key == 'autostart':
      if toggleState:
        copyFile(autoStartSrc, autoStartDst)
        notify.send(_('Yandex.Disk Indicator'), _('Auto-start ON'))
      else:
        deleteFile(autoStartDst)
        notify.send(_('Yandex.Disk Indicator'), _('Auto-start OFF'))
    elif key == 'fmextensions':
      if not button.get_inconsistent():         # It is a first call
        if not activateActions():               # When activation/deactivation is not success:
          notify.send(_('Yandex.Disk Indicator'),
                      _('ERROR in setting up of file manager extensions'))
          toggleState = not toggleState         # revert settings back
          button.set_inconsistent(True)         # set inconsistent state to detect second call
          button.set_active(toggleState)        # set check-button to reverted status
          # set_active will raise again the 'toggled' event
      else:                                     # This is a second call
        button.set_inconsistent(False)          # Just remove inconsistent status
    elif key == 'read-only':
      ow.set_sensitive(toggleState)

class LockFile(object):         # LockFile

  def __init__(self, fileName):
    ### Check for already running instance of the indicator application in user space ###
    self.fileName = fileName
    logger.debug('Lock file is:%s' % self.fileName)
    try:                                                          # Open lock file for write
      self.lockFile = open(self.fileName, 'wt')
      fcntl.flock(self.lockFile, fcntl.LOCK_EX | fcntl.LOCK_NB)   # Try to acquire exclusive lock
      logger.debug('Lock file succesfully locked.')
    except:                                                       # File is already locked
      sys.exit(_('The indicator instance is already running.\n'+
                 '(file %s is locked by another process)') % self.fileName)
    self.lockFile.write('%d\n' % os.getpid())
    self.lockFile.flush()

  def release(self):
    fcntl.flock(self.lockFile, fcntl.LOCK_UN)
    self.lockFile.close()
    logger.debug('Lock file %s successfully unlocked.' % self.fileName)
    deleteFile(self.fileName)
    logger.debug('Lock file %s successfully deleted.' % self.fileName)

def appExit(msg = None):        # Exit from application (it closes all indicators)
  for i in indicators:
    i.exit()
  flock.release()
  sys.exit(msg)

def activateActions():          # Install/deinstall file extensions
  activate = config["fmextensions"]
  result = False

  # Package manager check
  if subprocess.call("hash dpkg>/dev/null 2>&1", shell=True)==0:
    logger.info("dpkg detected")
    pm = 'dpkg -s '
  elif subprocess.call("hash rpm>/dev/null 2>&1", shell=True)==0:
    logger.info("rpm detected")
    pm = 'rpm -qi '
  elif subprocess.call("hash pacman>/dev/null 2>&1", shell=True)==0:
    logger.info("Pacman detected")
    pm = 'pacman -Qi '
  elif subprocess.call("hash zypper>/dev/null 2>&1", shell=True)==0:
    logger.info("Zypper detected")
    pm = 'zypper info '
  elif subprocess.call("hash emerge>/dev/null 2>&1", shell=True)==0:
    logger.info("Emerge detected")
    pm = 'emerge -pv '
  else:
    logger.info("Your package manager is not supported. Installing FM extensions is not possible.")
    return result
  # --- Actions for Nautilus ---
  ret = subprocess.call([pm + "nautilus>/dev/null 2>&1"], shell=True)
  logger.info("Nautilus installed: %s" % str(ret == 0))
  if ret == 0:
    ver = subprocess.check_output(["lsb_release -r | sed -n '1{s/[^0-9]//g;p;q}'"], shell=True)
    if ver != '' and int(ver) < 1210:
      nautilusPath = ".gnome2/nautilus-scripts/"
    else:
      nautilusPath = ".local/share/nautilus/scripts"
    logger.debug(nautilusPath)
    if activate:        # Install actions for Nautilus
      try:
        copyFile(pathJoin(installDir, "fm-actions/Nautilus_Nemo/publish"),
                 pathJoin(userHome,nautilusPath, _("Publish via Yandex.Disk")))
        copyFile(pathJoin(installDir, "fm-actions/Nautilus_Nemo/unpublish"),
                 pathJoin(userHome, nautilusPath, _("Unpublish from Yandex.disk")))
        result = True
      except:
        pass
    else:               # Remove actions for Nautilus
      try:
        deleteFile(pathJoin(userHome, nautilusPath, _("Publish via Yandex.Disk")))
        deleteFile(pathJoin(userHome, nautilusPath, _("Unpublish from Yandex.disk")))
        result = True
      except:
        pass
  # --- Actions for Nemo ---
  ret = subprocess.call([pm + "nemo>/dev/null 2>&1"], shell=True)
  logger.info("Nemo installed: %s" % str(ret == 0))
  if ret == 0:
    if activate:        # Install actions for Nemo
      try:
        copyFile(pathJoin(installDir, "fm-actions/Nautilus_Nemo/publish"),
                 pathJoin(userHome, ".local/share/nemo/scripts", _("Publish via Yandex.Disk")))
        copyFile(pathJoin(installDir, "fm-actions/Nautilus_Nemo/unpublish"),
                 pathJoin(userHome, ".local/share/nemo/scripts", _("Unpublish from Yandex.disk")))
        result = True
      except:
        pass
    else:               # Remove actions for Nemo
      try:
        deleteFile(pathJoin(userHome, ".gnome2/nemo-scripts", _("Publish via Yandex.Disk")))
        deleteFile(pathJoin(userHome, ".gnome2/nemo-scripts", _("Unpublish from Yandex.disk")))
        result = True
      except:
        pass
  # --- Actions for Thunar ---
  ret = subprocess.call([pm + "thunar>/dev/null 2>&1"], shell=True)
  logger.info("Thunar installed: %s" % str(ret == 0))
  if ret == 0:
    ucaPath = pathJoin(userHome, ".config/Thunar/uca.xml")
    if activate:        # Install actions for Thunar
      try:
        if subprocess.call(["grep '" + _("Publish via Yandex.Disk") + "' " +
                            ucaPath + " >/dev/null 2>&1"],
                           shell=True) != 0:
          subprocess.call(["sed", "-i", "s/<\/actions>/<action><icon>folder-publicshare<\/icon>" +
                         '<name>"' + _("Publish via Yandex.Disk") +
                         '"<\/name><command>yandex-disk publish %f | xclip -filter -selection' +
                         ' clipboard; zenity --info ' +
                         '--window-icon=\/usr\/share\/yd-tools\/icons\/yd-128.png ' +
                         '--title="Yandex.Disk" --ok-label="' + _('Close') + '" --text="' +
                         _('URL to file: %f was copied into clipboard.') +
                         '"<\/command><description><\/description><patterns>*<\/patterns>' +
                         '<directories\/><audio-files\/><image-files\/><other-files\/>' +
                         "<text-files\/><video-files\/><\/action><\/actions>/g", ucaPath])
        if subprocess.call(["grep '" + _("Unpublish from Yandex.disk") + "' " +
                            ucaPath + " >/dev/null 2>&1"],
                            shell=True) != 0:
          subprocess.call(["sed", "-i", "s/<\/actions>/<action><icon>folder<\/icon><name>\"" +
                         _("Unpublish from Yandex.disk") +
                         '"<\/name><command>zenity --info ' +
                         '--window-icon=\/usr\/share\/yd-tools\/icons\/yd-128_g.png --ok-label="' +
                         _('Close') + '" --title="Yandex.Disk" --text="' +
                         _("Unpublish from Yandex.disk") +
                         ': \`yandex-disk unpublish %f\`"<\/command>' +
                         '<description><\/description><patterns>*<\/patterns>' +
                         '<directories\/><audio-files\/><image-files\/><other-files\/>' +
                         "<text-files\/><video-files\/><\/action><\/actions>/g", ucaPath])
        result = True
      except:
        pass
    else:               # Remove actions for Thunar
      try:
        subprocess.call(["sed", "-i", "s/<action><icon>.*<\/icon><name>\"" +
                         _("Publish via Yandex.Disk") + "\".*<\/action>//", ucaPath])
        subprocess.call(["sed", "-i", "s/<action><icon>.*<\/icon><name>\"" +
                         _("Unpublish from Yandex.disk") + "\".*<\/action>//", ucaPath])
        result = True
      except:
        pass

  # --- Actions for Dolphin ---
  ret = subprocess.call([pm + "dolphin>/dev/null 2>&1"], shell=True)
  logger.info("Dolphin installed: %s" % str(ret == 0))
  if ret == 0:
    if activate:        # Install actions for Dolphin
      try:
        makedirs(pathJoin(userHome, '.local/share/kservices5/ServiceMenus'))
        copyFile(pathJoin(installDir, "fm-actions/Dolphin/ydpublish.desktop"),
                 pathJoin(userHome, ".local/share/kservices5/ServiceMenus/ydpublish.desktop"))
        result = True
      except:
        pass
    else:               # Remove actions for Dolphin
      try:
        deleteFile(pathJoin(userHome, ".local/share/kservices5/ServiceMenus/ydpublish.desktop"))
        result = True
      except:
        pass
  # --- Actions for Pantheon-files ---
  ret = subprocess.call([pm + "pantheon-files>/dev/null 2>&1"], shell=True)
  logger.info("Pantheon-files installed: %s" % str(ret == 0))
  if ret == 0:
    ctrs_path = "/usr/share/contractor/"
    if activate:        # Install actions for Pantheon-files
      src_path = pathJoin(installDir, "fm-actions", "pantheon-files")
      ctr_pub = pathJoin(src_path ,"yandex-disk-indicator-publish.contract")
      ctr_unpub = pathJoin(src_path ,"yandex-disk-indicator-unpublish.contract")
      res = subprocess.call(["gksudo", "-D", "yd-tools", "cp", ctr_pub, ctr_unpub, ctrs_path])
      if res == 0:
        result = True
      else:
        logger.error("Cannot enable actions for Pantheon-files")
    else:               # Remove actions for Pantheon-files
      res = subprocess.call(["gksudo", "-D", "yd-tools", "rm",
              pathJoin(ctrs_path, "yandex-disk-indicator-publish.contract"),
              pathJoin(ctrs_path, "yandex-disk-indicator-unpublish.contract")])
      if res == 0:
        result = True
      else:
        logger.error("Cannot disable actions for Pantheon-files")

  return result

def argParse():                 # Parse command line arguments
  parser = argparse.ArgumentParser(description=_('Desktop indicator for yandex-disk daemon'),
                                   add_help=False)
  group = parser.add_argument_group(_('Options'))
  group.add_argument('-l', '--log', type=int, choices=range(10, 60, 10),
            dest='level', default=30, help=_('Sets the logging level: ' +
                   '10 - to show all messages (DEBUG), ' +
                   '20 - to show all messages except debugging messages (INFO), ' +
                   '30 - to show all messages except debugging and info messages (WARNING), ' +
                   '40 - to show only error and critical messages (ERROR), ' +
                   '50 - to show critical messages only (CRITICAL). Default: 30'))
  group.add_argument('-c', '--config', dest='cfg', metavar='path', default='',
            help=_('Path to configuration file of YandexDisk daemon. ' +
                   'This daemon will be added to daemons list' +
                   ' if it is not in the current configuration.' +
                   'Default: \'\''))
  group.add_argument('-r', '--remove', dest='rcfg', metavar='path', default='',
            help=_('Path to configuration file of daemon that should be removed' +
                   ' from daemos list. Default: \'\''))
  group.add_argument('-h', '--help', action='help', help=_('Show this help message and exit'))
  group.add_argument('-v', '--version', action='version', version='%(prog)s v.' + appVer,
            help=_('Print version and exit'))
  return parser.parse_args()

def checkAutoStart(path):       # Check that auto-start is enabled
  if pathExists(path):
    with open(path, 'rt') as f:
      attr = re.findall(r'\nHidden=(.+)|\nX-GNOME-Autostart-enabled=(.+)', f.read())
      if attr:
        i = {'Unity':1, 'KDE':0, 'XFCE':0, 'Pantheon':1}.get(os.getenv('XDG_CURRENT_DESKTOP'), 0)
        if attr[0][i] and attr[0][i] == ('true' if i else 'false'):
          return True
      else:
        return True
  return False

###################### MAIN #########################
if __name__ == '__main__':
  # Application constants
  appName = 'yandex-disk-indicator'
  # See appVer in the beginnig of the code
  appHomeName = 'yd-tools'
  installDir = pathJoin('/usr/share', appHomeName)
  userHome = os.getenv("HOME")
  logo = pathJoin(installDir, 'icons/yd-128.png')
  configPath = pathJoin(userHome, '.config', appHomeName)
  # Define .desktop files locations for indicator auto-start facility
  autoStartSrc = '/usr/share/applications/Yandex.Disk-indicator.desktop'
  autoStartDst = pathJoin(userHome, '.config/autostart/Yandex.Disk-indicator.desktop')

  # Initialize logging
  logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s')
  logger = logging.getLogger('')

  # Setup localization
  # Load translation object (or NullTranslations) and define _() function.
  gettext.translation(appName, '/usr/share/locale', fallback=True).install()

  # Get command line arguments or their default values
  args = argParse()

  # Set user specified logging level
  logger.setLevel(args.level)

  # Report app version and logging level
  logger.info('%s v.%s' % (appName, appVer))
  logger.debug('Logging level: '+str(args.level))

  # Application configuration
  '''
  User configuration is stored in ~/.config/<appHomeName>/<appName>.conf file.
  This file can contain comments (line starts with '#') and config values in
  form: key=value[,value[,value ...]] where keys and values can be quoted ("...") or not.
  The following key words are reserved for configuration:
    autostart, notifications, theme, fmextensions and daemons.

  The dictionary 'config' stores the config settings for usage in code. Its values are saved to
  config file on exit from the Menu.Preferences dialogue or when there is no configuration file
  when application starts.

  Note that daemon settings ('dir', 'read-only', 'overwrite' and 'exclude_dir') are stored
  in ~/ .config/yandex-disk/config.cfg file. They are read in YDDaemon.__init__() method
  (in dictionary YDDaemon.config). Their values are saved to daemon config file also
  on exit from Menu.Preferences dialogue.

  Additionally 'startonstartofindicator' and 'stoponexitfromindicator' values are added into daemon
  configuration file to provide the functionality of obsolete 'startonstart' and 'stoponexit'
  values for each daemon individually.
  '''
  config = Config(pathJoin(configPath, appName + '.conf'))
  # Read some settings to variables, set default values and update some values
  config['autostart'] = checkAutoStart(autoStartDst)
  # Setup on-screen notification settings from config value
  config.setdefault('notifications', True)
  config.setdefault('theme', False)
  config.setdefault('fmextensions', True)
  config.setdefault('daemons', '~/.config/yandex-disk/config.cfg')
  # Is it a first run?
  if not config.readSuccess:
    logging.info('No config, probably it is a first run.')
    # Create application config folders in ~/.config
    try:
      makedirs(configPath)
      makedirs(pathJoin(configPath, 'icons/light'))
      makedirs(pathJoin(configPath, 'icons/dark'))
      # Copy icon themes readme to user config catalogue
      copyFile(pathJoin(installDir, 'icons/readme'), pathJoin(configPath, 'icons/readme'))
    except:
      sys.exit('Can\'t create configuration files in %s' % configPath)
    # Activate indicator automatic start on system start-up
    if not pathExists(autoStartDst):
      try:
        makedirs(pathJoin(userHome, '.config/autostart'))
        copyFile(autoStartSrc, autoStartDst)
        config['autostart'] = True
      except:
        logger.error('Can\'t activate indicator automatic start on system start-up')

    # Activate FM actions according to config (as it is first run)
    activateActions()
    # Save config with default settings
    config.save()

  # Add new daemon if it is not in current list
  daemons = CVal(config['daemons'])
  if args.cfg and args.cfg not in daemons:
    daemons.add(args.cfg)
    config.changed = True
  # Remove daemon if it is in the current list
  if args.rcfg and args.rcfg in daemons:
    daemons.remove(args.rcfg)
    config.changed = True
  # Check that at least one daemon is in the daemons list
  if not daemons:
    sys.exit(_('No daemons specified.\nCheck correctness of -r and -c options.'))
  # Update config if daemons list has been changed
  if config.changed:
    config['daemons'] = daemons.get()
    # Update configuration file
    config.save()

  # Check for already running instance of the indicator application with the same config
  flock = LockFile(pathJoin(configPath, 'pid'))

  # Make indicator objects for each daemon in daemons list
  indicators = []
  for d in daemons:
    indicators.append(Indicator(d.replace('~', userHome),
                                _('#%d ')%len(indicators) if len(daemons) > 1 else ''))

  # Notification engine for application messages (it is used in Preferences dialogue)
  notify = Notification(appName, config['notifications'])

  # Start GTK Main loop
  Gtk.main()
