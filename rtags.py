import sublime
import sublime_plugin
import subprocess
import threading
import re

import xml.etree.ElementTree as etree

# sublime-rtags settings
settings = None
# path to rc utility
RC_PATH = ''


def run_rc(switch, input=None, *args):
  p = subprocess.Popen([RC_PATH,
                         '--silent-query',
                         switch,                         
                         ] + list(args),
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stdin=subprocess.PIPE)
  print (' '.join(p.args))
  return p.communicate(input=input)

# TODO refactor somehow to remove global vars
class NavigationHelper(object):
  NAVIGATION_REQUESTED = 1
  NAVIGATION_DONE = 2
  def __init__(self):
    # store navigation/references output here
    self.data = []
    # navigation indicator, possible values are:
    # - NAVIGATION_REQUESTED
    # - NAVIGATION_DONE
    self.flag = NavigationHelper.NAVIGATION_DONE
    # flag is set when view has been modified
    # TODO check for more elegant solution
    self.is_modified = False


class RConnectionThread(threading.Thread):
  def notify(self):
    global navigation_helper
    navigation_helper.flag = NavigationHelper.NAVIGATION_DONE
    # do navigation
    print ('notify!')
    # TODO this doesn't work
    sublime.run_command('rtags_location', {'switch': '-l'})

  def run(self):
    p = subprocess.Popen([RC_PATH, '-m', '--silent-query'],
      stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    # `rc -m` will feed stdout with xml like this:
    # 
    # <?xml version="1.0" encoding="utf-8"?>
    #  <checkstyle>
    #   <file name="/home/ramp/tmp/pthread_simple.c">
    #    <error line="54" column="5" severity="warning" message="implicit declaration of function 'sleep' is invalid in C99"/>
    #    <error line="59" column="5" severity="warning" message="implicit declaration of function 'write' is invalid in C99"/>
    #    <error line="60" column="5" severity="warning" message="implicit declaration of function 'lseek' is invalid in C99"/>
    #    <error line="78" column="7" severity="warning" message="implicit declaration of function 'read' is invalid in C99"/>
    #   </file>
    #  </checkstyle>
    # <?xml version="1.0" encoding="utf-8"?>
    # <progress index="1" total="1"></progress>
    # 
    # So we need to split xml chunks somehow
    # Will start by looking for opening tag (<checkstyle, <progress)
    # and parse accumulated xml when we encounter closing tag 
    # TODO deal with < /> style tags
    rgxp = re.compile(r'<(\w+)')
    buffer = '' # xml to be parsed
    start_tag = ''
    while True:
      # read stdout line by line
      line = p.stdout.readline().decode('utf-8')
      if not start_tag:
        start_tag = re.findall(rgxp, line)
        start_tag = start_tag[0] if len(start_tag) else ''
      buffer += line
      if '</{}>'.format(start_tag) in line:
        tree = etree.fromstring(buffer)
        # OK, we received some chunk
        # check if it is progress update
        if tree.tag == 'progress':
          # notify about event
          print (tree.tag)
          self.notify()
        buffer = ''
        start_tag = ''



def get_view_text(view):
  return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")

reg = r'(\S+):(\d+):(\d+):(.*)'
class RtagsBaseCommand(sublime_plugin.TextCommand):
  def run(self, edit, switch, *args, **kwargs):
    # check if file needs reindexing
    global navigation_helper
    if self.view.is_dirty() and navigation_helper.is_modified:
      print ('request reindex')
      # TODO check why it's requesting reindex for second, third.. time
      self._reindex(self.view.file_name())
      navigation_helper.flag = NavigationHelper.NAVIGATION_REQUESTED

    # only do navigation when navigation is done
    if navigation_helper.flag != NavigationHelper.NAVIGATION_DONE:
      return

    out, err = run_rc(switch, None, self._query(*args, **kwargs))
    print (out, err)
    items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
    self.last_references = items
    def out_to_items(item):
      (file, line, _, usage) = re.findall(reg, item)[0]
      return [usage.strip(), "{}:{}".format(file.split('/')[-1], line)]
    items = list(map(out_to_items, items))
    if len(items) == 1:
      self.on_select(0)
      return
    self.view.window().show_quick_panel(items, self.on_select)

  def _reindex(self, filename):
    run_rc('-V', get_view_text(self.view), filename, 
      '--unsaved-file', '{}:{}'.format(filename, self.view.size()))

  def on_select(self, res):
    if res == -1:
      return
    (file, line, col, _) = re.findall(reg, self.last_references[res])[0]
    view = self.view.window().open_file('%s:%s' % (file, line), sublime.ENCODED_POSITION)

  def _query(self, *args, **kwargs):
    return ''

class RtagsSymbolNameCommand(RtagsBaseCommand):
  def _query(self, *args, **kwargs):
    return self.view.substr(self.view.word(self.view.sel()[0]))


class RtagsLocationCommand(RtagsBaseCommand):
  def _query(self, *args, **kwargs):
    row, col = self.view.rowcol(self.view.sel()[0].a)
    return '{}:{}:{}'.format(self.view.file_name(),
                             row+1, col+1)

class RtagsNavigationListener(sublime_plugin.EventListener):
  def on_modified(self, view):
    global navigation_helper
    if view.scope_name(0).split()[0] in ('source.c++',
                                                'source.c'):
      navigation_helper.is_modified = True
    
  def on_post_save(self, v):
    # run rc --check-reindex to reindex just saved files
    run_rc('-x')
    global navigation_helper
    navigation_helper.is_modified = False
    
class RtagsCompleteListener(sublime_plugin.EventListener):
  # TODO refactor
  def _query(self, *args, **kwargs):
    pos = args[0]
    row, col = self.view.rowcol(pos)
    return '{}:{}:{}'.format(self.view.file_name(),
                             row+1, col+1)

    
  
  def on_query_completions(self, v, prefix, location):
    switch = '-l' # rc's auto-complete switch
    self.view = v
    # libcland does auto-complete _only_ at whitespace and punctuation chars
    # so "rewind" location to that character
    location = location[0] - len(prefix)
    # do noting if called from not C/C++ code
    if v.scope_name(location).split()[0] not in ('source.c++',
                                       'source.c'):
      return []
    # We launch rc utility with both filename:line:col and filename:length
    # because we're using modified file which is passed via stdin (see --unsaved-file
    # switch)
    out, err = run_rc(switch, get_view_text(self.view), 
      self._query(location),
      '--unsaved-file',
      '{}:{}'.format(v.file_name(), v.size()), # filename:length
      '--synchronous-completions' # no async)
      )
    sugs = []
    for line in out.splitlines():
      # line is like this 
      # "process void process(CompletionThread::Request *request) CXXMethod"
      # "reparseTime int reparseTime VarDecl"
      # "dump String dump() CXXMethod"
      # "request CompletionThread::Request * request ParmDecl"
      # we want it to show as process()\tCXXMethod 
      # 
      # output is list of tuples: first tuple element is what we see in popup menu
      # second is what inserted into file. '$0' is where to place cursor.
      # TODO play with $1, ${2:int}, ${3:string} and so on
      elements = line.decode('utf-8').split()
      sugs.append(('{}\t{}'.format(' '.join(elements[1:-1]), elements[-1]),
                   '{}$0'.format(elements[0])))

    # inhibit every possible auto-completion 
    return sugs, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS


def update_settings():
  globals()['settings'] = sublime.load_settings('sublime-rtags.sublime-settings')
  globals()['RC_PATH'] = settings.get('rc_path', 'rc')

def init():
  update_settings()

  globals()['navigation_helper'] = NavigationHelper()
  thread = RConnectionThread()
  # TODO how do we stop it?
  thread.start()
  settings.add_on_change('rc_path', update_settings)

def plugin_loaded():
  sublime.set_timeout(init, 200)
