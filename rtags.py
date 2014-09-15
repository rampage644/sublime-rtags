import sublime
import sublime_plugin
import subprocess
import re

s = sublime.load_settings('sublime-rtags.sublime-settings')
s.add_on_change('rc_path', update_settings)
RC_PATH = s.get('rc_path', 'rc')

def update_settings():
  global RC_PATH
  RC_PATH = s.get('rc_path', 'rc')


reg = r'(\S+):(\d+):(\d+):(.*)'
class RtagsBaseCommand(sublime_plugin.TextCommand):
  def run(self, edit, switch, *args, **kwargs):
    p = subprocess.Popen([RC_PATH,
                         switch, 
                         self._query(*args, **kwargs), 
                         '--silent-query'],
     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
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
    p = subprocess.Popen([RC_PATH,
                         switch, 
                         self._query(location), # filename:line:col
                         '--silent-query', # no query logging
                         '--unsaved-file',
                         '{}:{}'.format(v.file_name(), v.size()), # filename:length
                         '--synchronous-completions' # no async
                         ],
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stdin=subprocess.PIPE)
    # TODO research encoding, probably get from sublime
    out, err = p.communicate(input=bytes(v.substr(sublime.Region(0, v.size())), "utf-8"))
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