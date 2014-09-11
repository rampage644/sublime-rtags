import sublime
import sublime_plugin
import subprocess
import re

BIN = '/home/ramp/mnt/git/rtags/build/bin/rc'
# pth_sleep
reg = r'(\S+):(\d+):(\d+):(.*)'
class RtagsCommand(sublime_plugin.TextCommand):
  def run(self, edit, switch):
    p = subprocess.Popen([BIN,
                         switch, 
                         self.view.substr(self.view.word(self.view.sel()[0])), 
                         '--silent-query'],
     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
    self.last_references = items
    def out_to_items(item):
      (file, _, _, usage) = re.findall(reg, item)[0]
      return [file.split('/')[-1], usage.strip()]
    items = list(map(out_to_items, items))
    self.view.window().show_quick_panel(items, self.on_select)

  def on_select(self, res):
    (file, line, col, _) = re.findall(reg, self.last_references[res])[0]
    view = self.view.window().open_file('%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)
    self.view.window().focus_view(view)
    view.sel().clear()
    p = view.text_point(int(line)-1, 0)
    print(p)
    view.sel().add(sublime.Region(p))
