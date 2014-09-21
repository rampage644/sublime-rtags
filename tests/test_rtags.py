#!/usr/bin/env python

import sublime
import sublime_plugin

import os
import subprocess
import sys
import unittest
import inspect
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
    self.foo_h_view.close()
    self.foo_cxx_view.close()

  def test_goto(self):
    s = self.foo_cxx_view.sel()
    tp = self.foo_cxx_view.text_point(19, 20)
    s.clear()
    s.add(sublime.Region(tp))
    self.foo_cxx_view.run_command('rtags_location', {'switch':'-f'})
    s = self.foo_h_view.sel()
    self.assertEquals(s[0].a, self.foo_h_view.text_point(16, 0))

  def test_find_usage(self):
    tp = self.foo_h_view.text_point(16,12)
    self.assertFalse(tp == 0)
    s = self.foo_h_view.sel()
    s.clear()
    s.add(sublime.Region(tp))
    self.foo_h_view.run_command('rtags_location', {'switch':'-r'})
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
    self.assertEquals(len(completions), 8, msg=str(completions))
    # take only actual var name, chopping '$0'
    completions = [c[:-2] for descr,c in completions]
    self.assertListEqual(completions,
        ['method3', 'method1', 'method2', 'method4', 'var1', 'var2', 'var4', 'var5'])
    self.foo_cxx_view.run_command('undo')






