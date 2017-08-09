import collections
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


def run_rc(switches, input=None, *args):
    timeout = 0.5
    if settings != None:
        timeout = settings.get('rc_timeout', timeout)

    p = subprocess.Popen([RC_PATH] + switches + list(args),
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stdin=subprocess.PIPE)
    print(' '.join(p.args))
    return p.communicate(input=input, timeout=timeout)

# TODO refactor somehow to remove global vars


class NavigationHelper(object):
    NAVIGATION_REQUESTED = 1
    NAVIGATION_DONE = 2

    def __init__(self):
        # navigation indicator, possible values are:
        # - NAVIGATION_REQUESTED
        # - NAVIGATION_DONE
        self.flag = NavigationHelper.NAVIGATION_DONE
        # rc utility switches to use for callback
        self.switches = []
        # file contents that has been passed to reindexer last time
        self.data = ''
        # history of navigations
        # elements are tuples (filename, line, col)
        self.history = collections.deque()


class RConnectionThread(threading.Thread):

    def notify(self):
        sublime.active_window().active_view().run_command('rtags_location',
                                                          {'switches': navigation_helper.switches})

    def run(self):
        self.p = subprocess.Popen([RC_PATH, '-m', '--silent-query'],
                                  stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
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
        buffer = ''  # xml to be parsed
        start_tag = ''
        for line in iter(self.p.stdout.readline, b''):
            line = line.decode('utf-8')
            self.p.poll()
            if not start_tag:
                start_tag = re.findall(rgxp, line)
                start_tag = start_tag[0] if len(start_tag) else ''
            buffer += line
            if '</{}>'.format(start_tag) in line:
                tree = etree.fromstring(buffer)
                # OK, we received some chunk
                # check if it is progress update
                if (tree.tag == 'progress' and
                        tree.attrib['index'] == tree.attrib['total'] and
                        navigation_helper.flag == NavigationHelper.NAVIGATION_REQUESTED):
                    # notify about event
                    sublime.set_timeout(self.notify, 10)
                buffer = ''
                start_tag = ''
        self.p = None

    def stop(self):
        if self.is_alive():
            self.p.kill()
            self.p = None


def get_view_text(view):
    return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")


reg = r'(\S+):(\d+):(\d+):(.*)'


class RtagsBaseCommand(sublime_plugin.TextCommand):

    def run(self, edit, switches, *args, **kwargs):
        # do nothing if not called from supported code
        if not supported_file_type(self.view):
            return
        # file should be reindexed only when
        # 1. file buffer is dirty (modified)
        # 2. there is no pending reindexation (navigation_helper flag)
        # 3. current text is different from previous one
        # It takes ~40-50 ms to reindex 2.5K C file and
        # miserable amount of time to check text difference
        if (navigation_helper.flag == NavigationHelper.NAVIGATION_DONE and
                self.view.is_dirty() and
                navigation_helper.data != get_view_text(self.view)):
            navigation_helper.switches = switches
            navigation_helper.data = get_view_text(self.view)
            navigation_helper.flag = NavigationHelper.NAVIGATION_REQUESTED
            self._reindex(self.view.file_name())
            # never go further
            return

        out, err = run_rc(switches, None, self._query(*args, **kwargs))
        # dirty hack
        # TODO figure out why rdm responds with 'Project loading'
        # for now just repeat query
        if out == b'Project loading\n':
            def rerun():
                self.view.run_command('rtags_location', {'switches': switches})
            sublime.set_timeout_async(rerun, 500)
            return

        # drop the flag, we are going to navigate
        navigation_helper.flag = NavigationHelper.NAVIGATION_DONE
        navigation_helper.switches = []

        self._action(out, err)

    def _reindex(self, filename):
        run_rc(['-V'], get_view_text(self.view), filename,
               '--unsaved-file', '{}:{}'.format(filename, self.view.size()))

    def on_select(self, res):
        if res == -1:
            return
        (file, line, col, _) = re.findall(reg, self.last_references[res])[0]
        nrow, ncol = self.view.rowcol(self.view.sel()[0].a)
        navigation_helper.history.append(
            (self.view.file_name(), nrow + 1, ncol + 1))
        if len(navigation_helper.history) > int(settings.get('jump_limit', 10)):
            navigation_helper.history.popleft()
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        if res == -1:
            return
        (file, line, col, _) = re.findall(reg, self.last_references[res])[0]
        nrow, ncol = self.view.rowcol(self.view.sel()[0].a)
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def _query(self, *args, **kwargs):
        return ''

    def _validate(self, stdout, stderr):
        if stdout != b'Not indexed\n':
            return True

        self.view.window().show_quick_panel(
            ["Not indexed"],
            None,
            sublime.MONOSPACE_FONT,
            -1,
            None)

        return False

    def _action(self, stdout, stderr):
        if not self._validate(stdout, stderr):
            return

        # pretty format the results
        items = list(map(lambda x: x.decode('utf-8'), stdout.splitlines()))
        self.last_references = items

        def out_to_items(item):
            (file, line, _, usage) = re.findall(reg, item)[0]
            return [usage.strip(), "{}:{}".format(file.split('/')[-1], line)]
        items = list(map(out_to_items, items))

        # if there is only one result no need to show it to user
        # just do navigation directly
        if len(items) == 1:
            self.on_select(0)
            return
        # else show all available options
        self.view.window().show_quick_panel(
            items, self.on_select, sublime.MONOSPACE_FONT, -1, self.on_highlight)


class RtagsGoBackwardCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        try:
            file, line, col = navigation_helper.history.pop()
            view = self.view.window().open_file(
                '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)
        except IndexError:
            pass


class RtagsSymbolNameCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        return self.view.substr(self.view.word(self.view.sel()[0]))


class RtagsLocationCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        row, col = self.view.rowcol(self.view.sel()[0].a)
        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)


class RtagsSymbolInfoCommand(RtagsLocationCommand):
    panel_name = 'cursor'
    inforeg = r'(\S+):\s*(.+)'

    def filter_items(self, item):
        return re.match(self.inforeg, item)

    def _action(self, out, err):
        if not self._validate(out, err):
            return

        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        items = list(filter(self.filter_items, items))

        def out_to_items(item):
            (title, info) = re.findall(self.inforeg, item)[0]
            return [info.strip(), title.strip()]

        def out_file_to_items(item):
            (file, line, _, usage) = re.findall(reg, item)[0]
            return [usage.strip(), "{}:{}".format(file.split('/')[-1], line)]

        items = list(map(out_to_items, items))
        self.last_references = items

        self.view.window().show_quick_panel(
            items,
            None,
            sublime.MONOSPACE_FONT,
            -1,
            None)


class RtagsNavigationListener(sublime_plugin.EventListener):
    # def on_modified(self, view):
    #   if view.scope_name(0).split()[0] in ('source.c++',
    #                                               'source.c'):
    #     navigation_helper.flag =

    def on_post_save(self, v):
        # do nothing if not called from supported code
        if not supported_file_type(v):
            return
        # run rc --check-reindex to reindex just saved files
        run_rc(['-x'], None, v.file_name())

    def on_post_text_command(self, view, command_name, args):
        # do nothing if not called from supported code
        if not supported_file_type(view):
            return
        # if view get 'clean' after undo check if we need reindex
        if command_name == 'undo' and not view.is_dirty():
            run_rc(['-V'], None, view.file_name())


class RtagsCompleteListener(sublime_plugin.EventListener):
    # TODO refactor

    def _query(self, *args, **kwargs):
        pos = args[0]
        row, col = self.view.rowcol(pos)
        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)

    def on_query_completions(self, v, prefix, location):
        switches = ['-l']  # rc's auto-complete switch
        self.view = v
        # libcland does auto-complete _only_ at whitespace and punctuation chars
        # so "rewind" location to that character
        location = location[0] - len(prefix)

        # do nothing if not called from supported code
        if not supported_file_type(v):
            return []
        # We launch rc utility with both filename:line:col and filename:length
        # because we're using modified file which is passed via stdin (see --unsaved-file
        # switch)
        out, err = run_rc(switches, get_view_text(self.view),
                          self._query(location),
                          '--unsaved-file',
                          # filename:length
                          '{}:{}'.format(v.file_name(), v.size()),
                          '--synchronous-completions'  # no async)
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


def supported_file_type(view):
    if settings == None:
        return False
    file_types = settings.get('file_types', ["source.c", "source.c++"])
    return view.scope_name(view.sel()[0].a).split()[0] in file_types


def update_settings():
    globals()['settings'] = sublime.load_settings(
        'sublime-rtags.sublime-settings')
    globals()['RC_PATH'] = settings.get('rc_path', 'rc')


def init():
    update_settings()

    globals()['navigation_helper'] = NavigationHelper()
    globals()['rc_thread'] = RConnectionThread()
    rc_thread.start()
    settings.add_on_change('rc_path', update_settings)


def plugin_loaded():
    sublime.set_timeout(init, 200)


def plugin_unloaded():
    # stop `rc -m` thread
    sublime.set_timeout(rc_thread.stop, 100)
