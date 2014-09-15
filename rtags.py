import sublime
import sublime_plugin
import subprocess
import re

BIN = '/home/ramp/mnt/git/rtags/build/bin/rc'
# pth_sleep
reg = r'(\S+):(\d+):(\d+):(.*)'
class RtagsBaseCommand(sublime_plugin.TextCommand):
  def run(self, edit, switch, *args, **kwargs):
    p = subprocess.Popen([BIN,
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
    # We launch rc utility with both filename:line:col and filename:length
    # because we're using modified file which is passed via stdin (see --unsaved-file
    # switch)

    p = subprocess.Popen([BIN,
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
    # TODO research encoding, get from sublime
    out, err = p.communicate(input=bytes(v.substr(sublime.Region(0, v.size())), "utf-8"))
    sugs = [(b' '.join(el.split()[1:-1]).decode('ascii'),
            '{}'.format(el.split()[0].decode('ascii'))) for el in out.splitlines()]
    # inhibit every possible auto-completion 
    return sugs, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS