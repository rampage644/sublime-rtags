#!/usr/bin/env python

import sublime
import sublime_plugin

import os
import subprocess
import sys
import unittest
import inspect
import random
import time

sublime_rtags = sys.modules['sublime-rtags.rtags']

FOO_CXX = os.path.join(os.path.split(__file__)[0], 'data', 'foo.cxx')
FOO_H = os.path.join(os.path.split(__file__)[0], 'data', 'foo.h')


# DANGEROUS! should be exedcuted from non-main sublime thread!
def wait(view):
  while view.is_loading():
    time.sleep(0.05)

class FooTest(unittest.TestCase):
  def setUp(self):
    subprocess.call(['rc', '-c',
                     'g++', FOO_CXX])
    self.foo_h_view = sublime.active_window().open_file(FOO_H)
    self.foo_cxx_view = sublime.active_window().open_file(FOO_CXX)
    wait(self.foo_cxx_view)
    wait(self.foo_h_view)
    
  def tearDown(self):
    # reindex files!
    sublime_rtags.run_rc('-V')
    while self.foo_cxx_view.is_dirty():
      self.foo_cxx_view.run_command('undo')
    self.foo_cxx_view.close()
    while self.foo_h_view.is_dirty():
      self.foo_h_view.run_command('undo')
    self.foo_h_view.close()

  def test_goto(self):
    self._action(self.foo_cxx_view, 19, 20, '-f')
    s = self.foo_h_view.sel()
    self.assertEquals(s[0].a, self.foo_h_view.text_point(16, 0))

  def test_find_usage(self):
    self._action(self.foo_h_view, 16, 12, '-r')
    s = self.foo_cxx_view.sel()
    tp = self.foo_cxx_view.text_point(25, 0)
    self.assertEquals(s[0].a, tp)

  def test_complete(self):
    tp = self.foo_cxx_view.text_point(9, 0)
    self.foo_cxx_view.sel().clear()
    self.foo_cxx_view.sel().add(sublime.Region(tp))
    user_input = 'this->'
    self.foo_cxx_view.run_command('insert', {'characters':user_input})
    tp = self.foo_cxx_view.text_point(9, len(user_input))
    listen = sublime_rtags.RtagsCompleteListener()
    completions = listen.on_query_completions(self.foo_cxx_view, '', [tp])[0]
    self.assertEquals(len(completions), 9, msg=str(completions))
    # take only actual var name, chopping '$0'
    completions = [c[:-2] for descr,c in completions]
    self.assertListEqual(completions,
        ['method3', 'method1', 'method2', 'method4', 'var1', 'var2', 'var4', 'var5', 'FooClass'])
    self.foo_cxx_view.run_command('undo')

  def test_goto_unsaved(self):
    count = random.randint(1,10)
    self.foo_cxx_view.run_command('insert', {'characters':'\n' * count})
    self._action(self.foo_cxx_view, 19 + count, 20, '-f')
    # looks like sleeping helps with waiting async event
    time.sleep(1)
    s = self.foo_h_view.sel()
    self.assertEquals(s[0].a, self.foo_h_view.text_point(16, 0))

  def test_find_usage_unsaved(self):
    count = random.randint(1,10)
    self.foo_h_view.run_command('insert', {'characters':'\n' * count})
    self._action(self.foo_h_view, 16 + count, 12, '-r')
    time.sleep(1)
    s = self.foo_cxx_view.sel()
    tp = self.foo_cxx_view.text_point(25, 0)
    self.assertEquals(s[0].a, tp)

  def test_issue13(self):
    # insert count newlines at the beginning
    count = random.randint(1,10)
    self.foo_cxx_view.run_command('insert', {'characters':'\n' * count})
    self._action(self.foo_cxx_view, 19 + count, 20, '-f')
    # ok, now let's undo
    sublime.active_window().focus_view(self.foo_cxx_view)
    self.foo_cxx_view.run_command('undo')
    # do navigation again
    self._action(self.foo_cxx_view, 19, 20, '-f')
    s = self.foo_h_view.sel()
    self.assertEquals(s[0].a, self.foo_h_view.text_point(16, 0))
  
  def _action(self, view, row, col, switch):
    sublime.active_window().focus_view(view)
    s = view.sel()
    tp = view.text_point(row, col)
    s.clear()
    s.add(sublime.Region(tp))
    view.run_command('rtags_location', {'switch':switch})