#!/usr/bin/env python

"""
Python Clang AST Viewer

Clang AST Viewer shows the abstract syntax tree of a c/c++ file in a window.

Enter 'pyclasvi.py -h' to show the usage

PyClASVi is distributed under the MIT License, see LICENSE file.
"""

import sys

if sys.version_info.major == 2:
    import ttk
    import Tkinter as tk
    import tkFont
    import tkFileDialog
    import tkMessageBox
else: # python3
    import tkinter.ttk as ttk
    import tkinter as tk
    import tkinter.font as tkFont
    import tkinter.filedialog as tkFileDialog
    import tkinter.messagebox as tkMessageBox

import clang.cindex
import ctypes
import argparse
import inspect
import re


# Convert objects to a string.
# Some object have no suitable standard string conversation, so use this.
def toStr(data):
    if isinstance(data, bytes):     # Python3 clang binding sometimes return bytes instead of strings
        return data.decode('ascii') # ASCII should be default in C/C++ but what about comments
    elif ((data.__class__ == int)   # int but not bool, show decimal and hex
          or (sys.version_info.major) == 2 and isinstance(data, long)):
        if data < 0:                    # no negative hex values
            return str(data)
        else:
            return '{0} ({0:#010x})'.format(data)
    elif isinstance(data, clang.cindex.Cursor): # default output for cursors
        return '{0} ({1:#010x}) {2}'.format(data.kind.name,
                                             data.hash,
                                             data.displayname)
    elif isinstance(data, clang.cindex.SourceLocation):
        return 'file:   {0}\nline:   {1}\ncolumn: {2}\noffset: {3}'.format(
            data.file, data.line, data.column, data.offset)
    else:
        return str(data)


# Just join strings.
def join(*args):
    return ''.join(args)


# Join everything to a string
def xjoin(*args):
    return ''.join((str(a) for a in args))


# check if m is an instance methode
def is_instance_methode(m):
    return inspect.ismethod(m)


# has this instance methode only the self parameter?
def is_simple_instance_methode(m):
    argSpec = inspect.getargspec(m)
    return len(argSpec.args) == 1 # only self


# get methode definition like "(arg1, arg2)" as string
def get_methode_prototype(m):
    argSpec = inspect.getargspec(m)
    return inspect.formatargspec(*argSpec)


# check if obj is in list
def is_obj_in_stack(obj, objStack):
    for o in objStack:
        if o.__class__ == obj.__class__: # some compare function trow exception if types are not equal
            if o == obj:
                return True
    return False


# Cursor objects have a hash property but no __hash__ method
# You can use this class to make Cursor object hashable
class HashableObj:
    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return self.obj == other.obj

    def __hash__(self):
        return self.obj.hash


# Make widget scrollable by adding scrollbars to the right and below it.
# Of course parent is the parent widget of widget.
# If there are more than one widget inside the parent use widgetRow and widgetColumn
# to specify witch widget should be scrollable.
def make_scrollable(parent, widget, widgetRow=0, widgetColumn=0):
        vsb = ttk.Scrollbar(parent, orient='vertical',command=widget.yview)
        widget.configure(yscrollcommand=vsb.set)
        vsb.grid(row=widgetRow, column=widgetColumn+1, sticky='ns')

        hsb = ttk.Scrollbar(parent, orient='horizontal',command=widget.xview)
        widget.configure(xscrollcommand=hsb.set)
        hsb.grid(row=widgetRow+1, column=widgetColumn, sticky='we')


class AppOptions:
    """Hold application options (passed around to various components)"""
    def __init__(self, filename, auto_parse, parse_options, parse_cmd=None):
        self.filename = filename
        self.auto_parse = auto_parse
        self.parse_options = parse_options
        self.parse_cmd = parse_cmd


# Widget to handle all inputs (file name and parameters).
# Contain [Parse] Button to start parsing and fill result in output frames
class InputFrame(ttk.Frame):
    def __init__(self, options, master=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self.parseCmd = options.parse_cmd
        self.filename = tk.StringVar(value='')
        self.xValue = tk.StringVar(value=InputFrame._X_OPTIONS[0])       # Option starting with "-x"
        self.stdValue = tk.StringVar(value=InputFrame._STD_OPTIONS[0])   # Option starting with "-std"
        self.parseoptValue = tk.StringVar(value=options.parse_options)   # Option starting with default parsing options

        self._create_widgets()

    _SOURCEFILETYPES = (
        ('All source files', '.h', 'TEXT'),
        ('All source files', '.c', 'TEXT'),
        ('All source files', '.hh', 'TEXT'),
        ('All source files', '.hpp', 'TEXT'),
        ('All source files', '.hxx', 'TEXT'),
        ('All source files', '.h++', 'TEXT'),
        ('All source files', '.C', 'TEXT'),
        ('All source files', '.cc', 'TEXT'),
        ('All source files', '.cpp', 'TEXT'),
        ('All source files', '.cxx', 'TEXT'),
        ('All source files', '.c++', 'TEXT'),
        ('All files', '*'),
        )

    _FILETYPES = (
        ('Text files', '.txt', 'TEXT'),
        ('All files', '*'),
        )
    _X_OPTIONS = (
        'no -x',
        '-xc',
        '-xc++'
        )
    _STD_OPTIONS = (
        'no -std',
        '-std=c89',
        '-std=c90',
        '-std=iso9899:1990',
        '-std=iso9899:199409',
        '-std=gnu89',
        '-std=gnu90',
        '-std=c99',
        '-std=iso9899:1999',
        '-std=gnu99',
        '-std=c11',
        '-std=iso9899:2011',
        '-std=gnu11',
        '-std=c17',
        '-std=iso9899:2017',
        '-std=gnu17',
        '-std=c++98',
        '-std=c++03',
        '-std=gnu++98',
        '-std=gnu++03',
        '-std=c++11',
        '-std=gnu++11',
        '-std=c++14',
        '-std=gnu++14',
        '-std=c++17',
        '-std=gnu++17',
        '-std=c++2a',
        '-std=gnu++2a'
        )
    _PARSE_OPTIONS = {
        'Default'                     : clang.cindex.TranslationUnit.PARSE_NONE,
        'Detailed Processing'         : clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        'Incomplete'                  : clang.cindex.TranslationUnit.PARSE_INCOMPLETE,
        'Create precompiled preamble' : clang.cindex.TranslationUnit.PARSE_PRECOMPILED_PREAMBLE,
        'Skip function bodies'        : clang.cindex.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
        }

    def _create_widgets(self):
        self.rowconfigure(4, weight=1)
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text='Input file:').grid(row=0, sticky='w')
        fileFrame = ttk.Frame(self)
        fileFrame.columnconfigure(0, weight=1)
        fileFrame.grid(row=1, column=0, columnspan=2, sticky='we')
        filenameEntry = ttk.Entry(fileFrame, textvariable=self.filename)
        filenameEntry.grid(row=0, column=0, sticky='we')
        button = ttk.Button(fileFrame, text='...', command=self._on_select_file)
        button.grid(row=0, column=1)

        ttk.Label(self, text='Arguments:').grid(row=2, sticky='w')
        buttonFrame = ttk.Frame(self)
        buttonFrame.grid(row=3, column=0, columnspan=2, sticky='we')
        button = ttk.Button(buttonFrame, text='+ Include', command=self._on_include)
        button.grid()
        button = ttk.Button(buttonFrame, text='+ Define', command=self._on_define)
        button.grid(row=0, column=1)

        xCBox = ttk.Combobox(buttonFrame, textvariable=self.xValue,
                values=InputFrame._X_OPTIONS)
        xCBox.bind('<<ComboboxSelected>>', self._on_select_x)
        xCBox.grid(row=0, column=2)

        stdCBox = ttk.Combobox(buttonFrame, textvariable=self.stdValue,
                values=InputFrame._STD_OPTIONS)
        stdCBox.bind('<<ComboboxSelected>>', self._on_select_std)
        stdCBox.grid(row=0, column=3)

        ttk.Label(buttonFrame, text=' Parsing mode: ').grid(row=0, column=4, sticky='w')
        parseOptCBox = ttk.Combobox(buttonFrame, textvariable=self.parseoptValue,
                values=list(InputFrame._PARSE_OPTIONS.keys()))
        parseOptCBox.grid(row=0, column=5)

        self.argsText = tk.Text(self, wrap='none')
        self.argsText.grid(row=4, sticky='nswe')
        make_scrollable(self, self.argsText, widgetRow=4, widgetColumn=0)

        buttonFrame = ttk.Frame(self)
        buttonFrame.grid(row=6, column=0, columnspan=2, sticky='we')
        buttonFrame.columnconfigure(2, weight=1)

        button = ttk.Button(buttonFrame, text='Load', command=self._on_file_load)
        button.grid(row=0, column=0)

        button = ttk.Button(buttonFrame, text='Save', command=self._on_file_save)
        button.grid(row=0, column=1)

        button = ttk.Button(buttonFrame, text='Parse', command=self.parseCmd)
        button.grid(row=0, column=2, sticky='we')

    def load_filename(self, filename):
        data = []
        with open(filename, 'r') as f:
            data = f.read()
        if data:
            lines = data.split('\n')
            if len(lines) > 0:
                self.set_filename(lines[0])
            self.set_args(lines[1:])

    def _on_file_load(self):
        fn = tkFileDialog.askopenfilename(filetypes=InputFrame._FILETYPES)
        if fn:
            self.load_filename(fn)

    def _on_file_save(self):
        with tkFileDialog.asksaveasfile(defaultextension='.txt', filetypes=InputFrame._FILETYPES) as f:
            f.write(join(self.get_filename(), '\n'))
            for arg in self.get_args():
                f.write(join(arg, '\n'))

    def _on_select_file(self):
        fn = tkFileDialog.askopenfilename(filetypes=self._SOURCEFILETYPES)
        if fn:
            self.set_filename(fn)

    def _on_include(self):
        dir = tkFileDialog.askdirectory()
        if dir:
            self.add_arg(join('-I', dir))

    def _on_define(self):
        self.add_arg('-D<name>=<value>')

    def _on_select_x(self, e):
        arg = self.xValue.get()
        if arg == InputFrame._X_OPTIONS[0]:
            arg = None
        self.set_arg('-x', arg)

    def _on_select_std(self, e):
        arg = self.stdValue.get()
        if arg == InputFrame._STD_OPTIONS[0]:
            arg = None
        self.set_arg('-std', arg)

    @staticmethod
    def get_parse_options(text):
        """Convert text value of a parse options to actual flag value"""
        return InputFrame._PARSE_OPTIONS.get(text, clang.cindex.TranslationUnit.PARSE_NONE)

    def set_parse_cmd(self, parseCmd):
        self.parseCmd = parseCmd

    def set_filename(self, fn):
        self.filename.set(fn)

    def get_filename(self):
        return self.filename.get()

    # Set a single arg starting with name.
    # Replace or erase the first arg if there is still one starting with name.
    # total is full argument string starting with name for replacement or None or empty string for erase.
    def set_arg(self, name, total):
        args = self.get_args()
        i = 0
        for arg in args:
            if arg[:len(name)] == name:
                break
            i += 1

        newArgs = args[:i]
        if total:
            newArgs.append(total)
        if i < len(args):
            newArgs.extend(args[i+1:])

        self.set_args(newArgs)

    # Set/replace all args
    def set_args(self, args):
        self.argsText.delete('1.0', 'end')
        for arg in args:
            self.add_arg(arg)

    def add_arg(self, arg):
        txt = self.argsText.get('1.0', 'end')
        if len(txt) > 1: # looks like there is always a trailing newline
            prefix = '\n'
        else:
            prefix = ''
        self.argsText.insert('end', join(prefix, arg))

    def get_args(self):
        args = []

        argStr = self.argsText.get('1.0', 'end')
        argStrList = argStr.split('\n')
        for arg in argStrList:
            if len(arg) > 0:
                args.append(arg)

        return args


# Widget to show all parse warnings and errors.
# The upper part shows the list, the lower part the Source position of selected diagnostics.
class ErrorFrame(ttk.Frame):
    def __init__(self, master=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self.filterValue=tk.StringVar(value=ErrorFrame._DIAG_STR_TAB[0]) # filter by severity
        self._create_widgets()
        self.errors = []                # list of diagnostics (also warnings not only errors)

    # _DIAG_LEVEL_TAB and _DIAG_STR_TAB must have the same size and order
    _DIAG_LEVEL_TAB = (
        clang.cindex.Diagnostic.Ignored,
        clang.cindex.Diagnostic.Note,
        clang.cindex.Diagnostic.Warning,
        clang.cindex.Diagnostic.Error,
        clang.cindex.Diagnostic.Fatal
        )
    _DIAG_STR_TAB = (
        xjoin(clang.cindex.Diagnostic.Ignored, ' Ignored'),
        xjoin(clang.cindex.Diagnostic.Note,    ' Note'),
        xjoin(clang.cindex.Diagnostic.Warning, ' Warning'),
        xjoin(clang.cindex.Diagnostic.Error,   ' Error'),
        xjoin(clang.cindex.Diagnostic.Fatal,   ' Fatal')
        )
    _DIAG_TAG_TAB = {clang.cindex.Diagnostic.Warning:('warning',),
                   clang.cindex.Diagnostic.Error:('error',),
                   clang.cindex.Diagnostic.Fatal:('fatal',)}

    def _create_widgets(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        charSize = tkFont.nametofont('TkHeadingFont').measure('#')

        pw = tk.PanedWindow(self, orient='vertical')
        pw.grid(row=0, column=0, sticky='nswe')

        frame = ttk.Frame(pw)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        buttonFrame = ttk.Frame(frame)
        buttonFrame.grid(row=0, column=0, columnspan=2, sticky='we')

        label = tk.Label(buttonFrame, text='Filter:')
        label.grid(row=0, column=0)
        filterCBox = ttk.Combobox(buttonFrame, textvariable=self.filterValue,
            values=ErrorFrame._DIAG_STR_TAB)
        filterCBox.bind('<<ComboboxSelected>>', self._filter)
        filterCBox.grid(row=0, column=1)

        self.errorTable = ttk.Treeview(frame, columns=('category', 'severity', 'spelling', 'location',
                                                       'option'))

        self.errorTable.tag_configure('warning', background='light yellow')
        self.errorTable.tag_configure('error', background='indian red')
        self.errorTable.tag_configure('fatal', background='dark red', foreground='white')

        self.errorTable.bind('<<TreeviewSelect>>', self._on_selection)
        self.errorTable.grid(row=1, column=0, sticky='nswe')
        make_scrollable(frame, self.errorTable, 1)
        pw.add(frame, stretch='always')

        self.errorTable.heading('#0', text='#')
        self.errorTable.column('#0', width=4*charSize, anchor='e', stretch=False)
        self.errorTable.heading('category', text='Category')
        self.errorTable.column('category', width=20*charSize, stretch=False)
        self.errorTable.heading('severity', text='Severity')
        self.errorTable.column('severity', width=8*charSize, stretch=False)
        self.errorTable.heading('spelling', text='Text')
        self.errorTable.column('spelling', width=50*charSize, stretch=False)
        self.errorTable.heading('location', text='Location')
        self.errorTable.column('location', width=50*charSize, stretch=False)
        self.errorTable.heading('option', text='Option')
        self.errorTable.column('option', width=20*charSize, stretch=False)

        self.fileOutputFrame = FileOutputFrame(pw)
        pw.add(self.fileOutputFrame, stretch='always')

    # Show selected diagnostic in source file
    def _on_selection(self, event):
        curItem = self.errorTable.focus()
        err = self.errors[int(curItem)]
        range1 = None
        for r in err.ranges:
            range1 = r
            break
        self.fileOutputFrame.set_location(range1, err.location)

    # Filter by selected severity
    def _filter(self, e=None):
        for i in self.errorTable.get_children():
            self.errorTable.delete(i)
        i = ErrorFrame._DIAG_STR_TAB.index(self.filterValue.get())
        diagLevel = ErrorFrame._DIAG_LEVEL_TAB[i]
        cnt = 0
        for err in self.errors:
            cnt = cnt + 1
            if err.severity < diagLevel:
                continue
            if err.severity in ErrorFrame._DIAG_LEVEL_TAB:
                i = ErrorFrame._DIAG_LEVEL_TAB.index(err.severity)
                serverity = ErrorFrame._DIAG_STR_TAB[i]
            else:
                serverity = str(err.severity)
            if err.severity in ErrorFrame._DIAG_TAG_TAB:
                tagsVal=ErrorFrame._DIAG_TAG_TAB[err.severity]
            else:
                tagsVal=()
            if err.location.file:
                location = '{} {}:{}'.format(err.location.file.name,
                                             err.location.line,
                                             err.location.offset)
            else:
                location = None
            self.errorTable.insert('', 'end', text=str(cnt), values=[
                join(str(err.category_number), ' ',  toStr(err.category_name)),
                serverity,
                err.spelling,
                location,
                err.option
                ],
                tags=tagsVal,
                iid=str(cnt-1))

    def clear(self):
        self.errors = []
        self.fileOutputFrame.clear()
        for i in self.errorTable.get_children():
            self.errorTable.delete(i)

    def set_errors(self, errors):
        self.clear()
        for err in errors:
            self.errors.append(err)
        self._filter()

        return len(self.errors)


# Widget to show the AST in a Treeview like folders in a file browser
# This widget is the master for current selected Cursor object.
# If you want to show an other Cursor call set_current_cursor(...)
class ASTOutputFrame(ttk.Frame):
    def __init__(self, master=None, selectCmd=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self._create_widgets()
        self.translationunit = None
        self.mapIIDtoCursor = {}        # Treeview use IIDs (stings) to identify a note,
        self.mapCursorToIID = {}        # so we need to map between IID and Cursor in both direction.
                                        # One Cursor may have a list of IIDs if several times found in AST.
        self.selectCmd = selectCmd      # Callback after selecting a Cursor

    def _create_widgets(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        charSize = tkFont.nametofont('TkFixedFont').measure('#')

        self.astView = ttk.Treeview(self, selectmode='browse')
        self.astView.tag_configure('default', font='TkFixedFont')
        self.astView.bind('<<TreeviewSelect>>', self._on_selection)

        make_scrollable(self, self.astView)

        self.astView.heading('#0', text='Cursor')
        self.astView.grid(row=0, column=0, sticky='nswe')

    def _on_selection(self, event):
        if self.selectCmd is not None:
            self.selectCmd()

    def set_select_cmd(self, cmd):
        self.selectCmd = cmd

    def get_current_iid(self):
        return self.astView.focus()

    # Return a single IID or a list of IIDs.
    def get_current_iids(self):
        cursor = self.get_current_cursor()
        if cursor is not None:
            return self.mapCursorToIID[HashableObj(cursor)]
        else:
            return None

    def get_current_cursor(self):
        curCursor = None
        curItem = self.astView.focus()
        if curItem:
            curCursor = self.mapIIDtoCursor[curItem]
        return curCursor

    def set_current_iid(self, iid):
        self.astView.focus(iid)
        self.astView.selection_set(iid)
        self.astView.see(iid)

    def set_current_cursor(self, cursor):
        iid = self.mapCursorToIID[HashableObj(cursor)]
        if isinstance(iid, list): # partly multimap
            iid = iid[0]
        self.set_current_iid(iid)

    def clear(self):
        for i in self.astView.get_children():
            self.astView.delete(i)
        self.translationunit = None
        self.mapIIDtoCursor = {}
        self.mapCursorToIID = {}

    def _insert_children(self, cursor, iid, deep=1):
        cntChildren = 0
        for childCursor in cursor.get_children():
            cntChildren = cntChildren + 1
            newIID = self.astView.insert(iid,
                                        'end',
                                        text=toStr(childCursor),
                                        tags=['default'])
            self.mapIIDtoCursor[newIID] = childCursor
            hCursor = HashableObj(childCursor)
            if hCursor in self.mapCursorToIID: # already in map, make a partly multimap
                self.cntDouble = self.cntDouble + 1
                data = self.mapCursorToIID[hCursor]
                if isinstance(data, str):
                    data = [data]
                    self.mapCursorToIID[hCursor] = data
                data.append(newIID)
                if len(data) > self.cntMaxDoubles:
                    self.cntMaxDoubles = len(data)
            else:
                self.mapCursorToIID[hCursor] = newIID
            self._insert_children(childCursor, newIID, deep+1)
            self.cntCursors = self.cntCursors + 1

        if cntChildren > 0:
            if cntChildren > self.cntMaxChildren:
                self.cntMaxChildren = cntChildren
            if deep > self.cntMaxDeep:
                self.cntMaxDeep = deep

    def set_translationunit(self, tu):
        self.cntCursors = 1
        self.cntDouble = 0
        self.cntMaxDoubles = 0
        self.cntMaxChildren = 0
        self.cntMaxDeep = 0
        self.clear()
        self.translationunit = tu
        root = tu.cursor
        iid = self.astView.insert('',
                                  'end',
                                  text=toStr(root),
                                  tags=['default'])
        self.mapIIDtoCursor[iid] = root
        self.mapCursorToIID[HashableObj(root)] = iid
        self._insert_children(root, iid)

        # some statistics
        print('AST has {0} cursors including {1} doubles.'.format(self.cntCursors, self.cntDouble))
        print('max doubles: {0}, max children {1}, max deep {2}'.format(
            self.cntMaxDoubles, self.cntMaxChildren, self.cntMaxDeep))

    # Search for IIDs matching to Cursors matching to kwargs.
    def search(self, **kwargs):
        result = []
        useCursorKind = kwargs['use_CursorKind']
        cursorKind = kwargs['CursorKind']
        spelling = kwargs['spelling']
        caseInsensitive = kwargs['caseInsensitive']
        useRegEx = kwargs['use_RexEx']
        if useRegEx:
            reFlags = 0
            if caseInsensitive:
                reFlags = re.IGNORECASE
            try:
                reObj = re.compile(spelling, reFlags)
            except Exception as e:
                tkMessageBox.showerror('Search RegEx', str(e))
                return result
        elif caseInsensitive:
            spelling = spelling.lower()

        for iid in self.mapIIDtoCursor:
            cursor = self.mapIIDtoCursor[iid]
            found = True
            if useCursorKind:
                found = cursorKind == cursor.kind.name
            if found:
                if useRegEx:
                    if not reObj.match(toStr(cursor.spelling)):
                        found = False

                elif caseInsensitive:
                    found = spelling == toStr(cursor.spelling).lower()
                else:
                    found = spelling == toStr(cursor.spelling)
            if found:
                result.append(iid)

        result.sort()

        return result


# Helper class to represent un-/folded sections in Text widget of CursorOutputFrame.
# One node is of type FoldSection.
# No Node will be removed even if a new selected cursor object have less section.
# Therefore if you open the next cursor with the same section hierarchy it this tree
# can remember witch section should be shown and witch not.
#
# Remark, this only works if always the same kind of object with the same attribute order is shown.
# An example:
# Obj A:Cursor                               B:Cursor                         C:WahtElse
#     +- brief_comment = None                +- brief_comment = "a function"  +- brief_comment = None
#     +- get_arguments:iterator => empty     +- get_arguments:iterator        |
#     |                                      |  +- [0]:Cursor                 |
#     |                                      |  +- [1]:Cursor                 |
#     +- spelling:sting = "a"                +- spelling:sting = "func"       +- spelling:sting = "x"
#
# Object A and B are fine, B create more active nodes in FoldSectionTree
# but the attribute order is identical. Object C have some same called attributes but in wrong order.
# If first B is shown with get_arguments (2nd attribute) open but spelling (3rd attribute) closed
# and than C was shown spelling (here 2nd attribute) will be open.
# If A is show some of the nodes representing the two sub Cursor in object B will be inactive.
class FoldSectionTree:
    def __init__(self):
        self.root = FoldSection(True)   # just a root node witch is always shown
        self.marker = None              # a singe section header (attribute name) can be highlighted

    def get_root(self):
        return self.root

    def set_marker(self, marker):
        self.marker = marker

    def get_marker(self):
        return self.marker

    def set_all_show(self, show):
        FoldSection.show_default = show
        self.root.set_all_show(show)

    # Deactivate all section but do not erase it, they still know if they should be shown or not.
    def clear_lines(self):
        self.root.clear_lines()

    # Find section starting at startLine in Text widget.
    def find_section(self, startLine):
        return self._find_section(startLine, self.root.members)

    def _find_section(self, startLine, sectionList):
        if sectionList:
            lastSec = None
            for sec in sectionList:
                if sec.startLine == 0:
                    break
                elif sec.startLine == startLine:
                    return sec
                elif sec.startLine < startLine:
                    lastSec = sec
                else:
                    break
            if lastSec is not None:
                return self._find_section(startLine, lastSec.members)
            else:
                return None
        else:
            return None


# Node in FoldSectionTree
class FoldSection:
    def __init__(self, show, deep=-1):
        self.startLine = 0      # if 0 this section is not active
        self.show = show        # fold or not
        self.members = None     # children
        self.parent = None
        self.childNr = -1       # child index from parent view
        self.deep = deep        # current deep in tree, root is -1, first real sections 0

    show_default = False # default section are closed

    # Map this section to starting text line in Text widget.
    # This also activate this section (startLine > 0).
    def set_line(self, startLine):
        self.startLine = startLine

    def set_show(self, show):
        self.show = show

    # Open this an all children sections.
    def set_all_show(self, show):
        self.show = show
        if self.members:
            for m in self.members:
                m.set_all_show(show)

    # Get the n-th children.
    # Remark, children (nodes) represent Cursor attributes in same order.
    # num may convert to attribute name to support different kind of objects in CursorOutputFrame.
    def get_child(self, num):
        if self.members is None:
            self.members = []

        while (num+1) > len(self.members):
            newFS = FoldSection(FoldSection.show_default, self.deep+1)
            newFS.parent = self
            newFS.childNr = num
            self.members.append(newFS)

        return self.members[num]

    # Deactivate this section and all children.
    def clear_lines(self):
        self.startLine = 0
        if self.members:
            for m in self.members:
                m.clear_lines()


# Widget to show nearly all attributes of a Cursor object
# Private member are ignored and other Cursors are just shown as link.
# If the attribute its self have attributes they are also up to a defined deep, so you have still a tree.
# So you have still a tree. This is not implemented by a Treewiew widget but just Text widget.
# The text widget gives you more layout possibilities but you have to implement the folding logic
# by your self. Therefore the classes FoldSectionTree and FoldSection are used which also
# implements some features missed in the Treeview widget.
class CursorOutputFrame(ttk.Frame):
    def __init__(self, master=None, selectCmd=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self._create_widgets()
        self.cursor = None
        self.selectCmd = selectCmd              # will be called on clicking a cursor link
        self.cursorList = []                    # list of cursor in same order as links are shown in text
        self.foldTree = FoldSectionTree()       # contains infos about foldable section (a single member)

    _MAX_DEEP = 8               # max deep of foldable sections / attributes
    _MAX_ITER_OUT = 25          # is a member is an iterator show just the first x elements
    _DATA_INDENT = '      '     # indentation for sub sections / attributes

    # ignore member with this types
    _IGNORE_TYPES = ('function',)

    def _create_widgets(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        defFont = tkFont.Font(font='TkFixedFont')
        defFontProp = defFont.actual()
        self.cursorText = tk.Text(self, wrap='none')
        self.cursorText.grid(row=0, sticky='nswe')
        self.cursorText.bind('<Button-3>', self._on_right_click)

        make_scrollable(self, self.cursorText)

        self.cursorText.tag_configure('attr_name', font=(defFontProp['family'], defFontProp['size'], 'bold'))
        self.cursorText.tag_bind('attr_name', '<ButtonPress-1>', self._on_attr_click)
        self.cursorText.tag_configure('attr_name_marked', background='lightblue')
        self.cursorText.tag_configure('attr_type', foreground='green')
        self.cursorText.tag_configure('attr_err', foreground='red')
        self.cursorText.tag_configure('link', foreground='blue')
        self.cursorText.tag_bind('link', '<ButtonPress-1>', self._on_cursor_click)
        self.cursorText.tag_bind('link', '<Enter>', self._on_link_enter)
        self.cursorText.tag_bind('link', '<Leave>', self._on_link_leave)
        self.cursorText.tag_configure('special', font=(defFontProp['family'], defFontProp['size'], 'italic'))

        for n in range(CursorOutputFrame._MAX_DEEP):
            self.cursorText.tag_configure(xjoin('section_header_', n), foreground='gray')
            self.cursorText.tag_bind(xjoin('section_header_', n), '<ButtonPress-1>', self._on_section_click)
            self.cursorText.tag_bind(xjoin('section_header_', n), '<Enter>', self._on_section_enter)
            self.cursorText.tag_bind(xjoin('section_header_', n), '<Leave>', self._on_section_leave)
            self.cursorText.tag_configure(xjoin('section_hidden_', n), elide=True)
            self.cursorText.tag_configure(xjoin('section_', n))

        self.cursorText.config(state='disabled')

    # Change mouse cursor over links.
    def _on_link_enter(self, event):
        self.cursorText.configure(cursor='hand1')

    # Reset mouse cursor after leaving links.
    def _on_link_leave(self, event):
        self.cursorText.configure(cursor='xterm')

    # Cursor link was clicked, run callback.
    def _on_cursor_click(self, event):
        if self.selectCmd is None:
            return

        curIdx = self.cursorText.index('@{0},{1}'.format(event.x, event.y))
        linkIdxs = list(self.cursorText.tag_ranges('link'))
        listIdx = 0

        for start, end in zip(linkIdxs[0::2], linkIdxs[1::2]):
            if (self.cursorText.compare(curIdx, '>=', start) and
                self.cursorText.compare(curIdx, '<', end)):
                cursor = self.cursorList[listIdx]
                self.selectCmd(cursor)
                break
            listIdx += 1

    # Mark clicked attribute name and store it in foldTree.
    def _on_attr_click(self, event):
        self.cursorText.tag_remove('attr_name_marked', '1.0', 'end')
        curIdx = self.cursorText.index('@{0},{1}'.format(event.x, event.y))
        curLine = curIdx.split('.')[0]

        curSec = self.foldTree.find_section(int(curLine))
        if curSec is not None:
            self.foldTree.set_marker(curSec)

        attr = self.cursorText.tag_nextrange('attr_name', join(curLine, '.0'))
        self.cursorText.tag_add('attr_name_marked', attr[0], attr[1])

    # Scroll text widget so marked attribute is shown.
    def goto_marker(self):
        curMarker = self.cursorText.tag_nextrange('attr_name_marked', '1.0')
        if curMarker:
            self.cursorText.see('end')          # first jump to the end, so also the lines ...
            self.cursorText.see(curMarker[0])   # ...after attribute name are shown

    # Show context menu.
    def _on_right_click(self, event):
        menu = tk.Menu(None, tearoff=0)
        menu.add_command(label='Expand all', command=self.expand_all)
        menu.add_command(label='Collapse all', command=self.collapse_all)
        menu.tk_popup(event.x_root, event.y_root)

    # Change mouse cursor over clickable [+]/[-] of a node of a foldable section.
    def _on_section_enter(self, event):
        self.cursorText.configure(cursor='arrow')

    # Reset mouse cursor.
    def _on_section_leave(self, event):
        self.cursorText.configure(cursor='xterm')

    # There was a click on [+]/[-], so we need to fold or unfold a section.
    def _on_section_click(self, event):
        curIdx = self.cursorText.index('@{0},{1}'.format(event.x, event.y))
        curLine = int(curIdx.split('.')[0])
        curSec = self.foldTree.find_section(curLine) # find clicked section in foldTree
        if curSec is None:
            return # should never happen

        # find the matching section tag
        curLev = curSec.deep
        next_section = self.cursorText.tag_nextrange(xjoin('section_', curLev), curIdx)

        if next_section: # should always be true
            self.cursorText.config(state='normal')
            cur_header = self.cursorText.tag_prevrange(xjoin('section_header_', curLev), next_section[0])
            next_hidden = self.cursorText.tag_nextrange(xjoin('section_hidden_', curLev), curIdx)
            self.cursorText.delete(join(cur_header[0], ' +1c'), join(cur_header[0], ' +2c'))
            newShow = next_hidden and (next_hidden == next_section)
            if newShow:
                self.cursorText.tag_remove(xjoin('section_hidden_', curLev), next_section[0], next_section[1])
                self.cursorText.insert(join(cur_header[0], ' +1c'), '-')
            else:
                self.cursorText.tag_add(xjoin('section_hidden_', curLev), next_section[0], next_section[1])
                self.cursorText.insert(join(cur_header[0], ' +1c'), '+')
            curSec.set_show(newShow)
            self.cursorText.config(state='disabled')

    # Expand all section (via context menu).
    def expand_all(self):
        self.foldTree.set_all_show(True)
        self.cursorText.config(state='normal')
        for n in range(CursorOutputFrame._MAX_DEEP):
            secs = self.cursorText.tag_ranges(xjoin('section_', n))
            for start, end in zip(secs[0::2], secs[1::2]):
                cur_header = self.cursorText.tag_prevrange(xjoin('section_header_', n), start)
                self.cursorText.delete(join(cur_header[0], ' +1c'), join(cur_header[0], ' +2c'))
                self.cursorText.tag_remove(xjoin('section_hidden_', n), start, end)
                self.cursorText.insert(join(cur_header[0], ' +1c'), '-')
        self.cursorText.config(state='disabled')

    # Collapse all sections (via context menu).
    def collapse_all(self):
        self.foldTree.set_all_show(False)
        self.cursorText.config(state='normal')
        for n in range(CursorOutputFrame._MAX_DEEP):
            secs = self.cursorText.tag_ranges(xjoin('section_', n))
            for start, end in zip(secs[0::2], secs[1::2]):
                cur_header = self.cursorText.tag_prevrange(xjoin('section_header_', n), start)
                self.cursorText.delete(join(cur_header[0], ' +1c'), join(cur_header[0], ' +2c'))
                self.cursorText.tag_add(xjoin('section_hidden_', n), start, end)
                self.cursorText.insert(join(cur_header[0], ' +1c'), '+')
        self.cursorText.config(state='disabled')

    def clear(self):
        self.cursorText.config(state='normal')
        self.cursorText.delete('1.0', 'end')
        self.cursorText.config(state='disabled')
        self.cursor = None
        self.cursorList = []

    # Output cursor with link in text widget.
    def _add_cursor(self, cursor):
        # we got an exception if we compare a Cursor object with an other none Cursor object like None
        # Therfore Cursor == None will not work so we use a try
        if isinstance(cursor, clang.cindex.Cursor):
            self.cursorText.insert('end',
                                toStr(cursor),
                                'link')
            self.cursorList.append(cursor)
        else:
            self.cursorText.insert('end', str(cursor))

    # Add a single attribute or a value of an iterable to the output.
    # This output contains a header and the value that can be fold/unfold.
    # if index is >= 0 a value of an iterable is outputted else an attribute.
    # Some attributes are skipped, so this function may output nothing.
    # The attributes name is attrName and it belongs to the last object in objStack.
    # foldNode contains FoldSection matching to current object the attribute belongs to.
    # For values of an iterable objStack also contains this value and foldeNode
    # belongs to the value. attrName may same useful name e.g. "[0]".
    def _add_attr(self, objStack, attrName, foldNode, index=-1):
        obj = objStack[-1]
        deep = len(objStack) - 1
        prefix = '\t' * deep
        isIterData = index >= 0

        # set default values
        attrData = None                 # attribute value for output
        attrDataTag = None              # special tag for special output format (None, attr_err, special)
        attrTypeTag = 'attr_type'       # tag for attribute name (attr_type, attr_err)

        if not isIterData:
            try:
                attrData = getattr(obj, attrName)
                attrType = attrData.__class__.__name__
                if attrType in CursorOutputFrame._IGNORE_TYPES:
                    return False # no new section created
            except BaseException as e:
                attrType = join(e.__class__.__name__, ' => do not use this')
                attrTypeTag = 'attr_err'
        else:
            attrData = obj
            attrType = attrData.__class__.__name__

        if (isinstance(obj, clang.cindex.Type)
            and (obj.kind == clang.cindex.TypeKind.INVALID)
            and (attrName in ('get_address_space', 'get_typedef_name'))):
            attrData = 'Do not uses this if kind is TypeKind.INVALID!'
            attrDataTag = 'attr_err'
        elif is_instance_methode(attrData):
            attrType = join(attrType,  ' ', get_methode_prototype(attrData))
            if is_simple_instance_methode(attrData):
                try:
                    attrData = attrData()
                    attrType = join(attrType, ' => ', attrData.__class__.__name__)
                except BaseException as e:
                    attrData = join(e.__class__.__name__, ' => do not use this')
                    attrDataTag = 'attr_err'
                if attrName == 'get_children':
                    cnt = 0
                    for c in attrData:
                        cnt = cnt+1
                    attrData = xjoin(cnt, ' children, see tree on the left')
                    attrDataTag = 'special'

        # start output, first line is always shown if parent section is also shown
        curIdx = self.cursorText.index('end -1c')
        curLine = int(curIdx.split('.')[0])
        foldNode.set_line(curLine)
        self.cursorText.insert('end', prefix)
        self.cursorText.insert('end', '[-] ', xjoin('section_header_', deep))

        if not isIterData:
            if self.foldTree.get_marker() == foldNode:
                attTags = ('attr_name', 'attr_name_marked')
            else:
                attTags = 'attr_name'
        else:
            attTags = ()
        self.cursorText.insert('end', attrName, attTags)
        self.cursorText.insert('end', ' (')
        self.cursorText.insert('end', attrType, attrTypeTag)
        self.cursorText.insert('end', '):\n')
        # first line done

        startIdx = self.cursorText.index('end -1c')

        # special behauviour for special attributes like functions or iterables
        if attrName in ('get_template_argument_kind',
                        'get_template_argument_type',
                        'get_template_argument_value',
                        'get_template_argument_unsigned_value'):
            nums = obj.get_num_template_arguments()
            if nums > 0:
                for n in range(nums):
                    result = attrData(n)
                    subFoldNode = foldNode.get_child(n)
                    objStack.append(result)
                    self._add_attr(objStack, xjoin('num=', n), subFoldNode, n)
                    objStack.pop()
            else:
                self.cursorText.insert('end', '\n')
        elif hasattr(attrData, '__iter__') and not isinstance(attrData, (str, bytes)):
            self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT, '[\n'))
            cnt = 0
            for d in attrData:
                if cnt < CursorOutputFrame._MAX_ITER_OUT:
                    subFoldNode = foldNode.get_child(cnt)
                    objStack.append(d)
                    self._add_attr(objStack, str(cnt), subFoldNode, cnt)
                    objStack.pop()
                else:
                    self.cursorText.insert('end',
                                           join(prefix,
                                                '   ',
                                                CursorOutputFrame._DATA_INDENT,
                                                'and some more...\n'),
                                           'special')
                    break
                cnt = cnt+1
            self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT, ']\n'))
        else:
            self._add_attr_data(objStack, foldNode, attrData, attrDataTag, isIterData)

        #self.cursorText.insert('end', '\n') # use this if you want an extra line witch can be hidden
        endIdx = self.cursorText.index('end -1c')
        #self.cursorText.insert('end', '\n') # use this if you want an extra line witch can't be hidden

        # add tags for the section needed to hide a section or find the position for later hidding
        self.cursorText.tag_add(xjoin('section_', deep), startIdx, endIdx)
        if not foldNode.show:
            cur_header = self.cursorText.tag_prevrange(xjoin('section_header_', deep), 'end')
            self.cursorText.delete(join(cur_header[0], ' +1c'), join(cur_header[0], ' +2c'))
            self.cursorText.insert(join(cur_header[0], ' +1c'), '+')
            self.cursorText.tag_add(xjoin('section_hidden_', deep), startIdx, endIdx)

        return True # new section created

    # Add a single attribute or a value of an iterable to the output.
    # This output contains only the value.
    # If isIterData is true a value of an iterable is outputted else an attribute.
    # objStack and foldNode have the same meaning like at function _add_attr.
    # attrData is the value and attrDataTag a tag for output format.
    def _add_attr_data(self, objStack, foldNode, attrData, attrDataTag, isIterData):
        deep = len(objStack) - 1
        prefix = '\t' * deep

        if isinstance(attrData, clang.cindex.Cursor):
            self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT))
            self._add_cursor(attrData)
            self.cursorText.insert('end', '\n')
        elif (isinstance(attrData, clang.cindex.Type)
              or isinstance(attrData, clang.cindex.SourceRange)
              or isinstance(attrData, clang.cindex.Token)):
            if isIterData:
                cmpStack = objStack[:-1]
            else:
                cmpStack = objStack
            if not is_obj_in_stack(attrData, cmpStack): #attrData not in objStack:
                if (deep+1) < CursorOutputFrame._MAX_DEEP:
                    objStack.append(attrData)
                    self._add_obj(objStack, foldNode)
                    objStack.pop()
                else:
                    self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT))
                    self.cursorText.insert('end',
                                          join('To deep to show ', toStr(attrData)),
                                          'special')
                    self.cursorText.insert('end', '\n')
            else:
                self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT))
                self.cursorText.insert('end',
                                       join(toStr(attrData), ' already shown!'),
                                       'special')
                self.cursorText.insert('end', '\n')
        else:
            lines = toStr(attrData).split('\n')
            for line in lines:
                self.cursorText.insert('end', join(prefix, CursorOutputFrame._DATA_INDENT))
                self.cursorText.insert('end', line, attrDataTag)
                self.cursorText.insert('end', '\n')

        return

    # Add nearly all attributes of last object in objStack to the output.
    # objStack contains the current clang object an all its parents starting from root.
    # foldNode contains FoldSection matching to current clang object.
    def _add_obj(self, objStack, foldNode):
        if objStack and (len(objStack) > 0):
            obj = objStack[-1]
            attrs = dir(obj)
            attIdx = 0
            for attrName in attrs:
                # ignore all starts with '_'
                if attrName[0] == '_':
                    continue
                subFoldNode = foldNode.get_child(attIdx)
                res = self._add_attr(objStack, attrName, subFoldNode)
                if res:
                    attIdx += 1

    # Set cursor for output.
    def set_cursor(self, c):
        self.foldTree.clear_lines()

        if not isinstance(c, clang.cindex.Cursor):
            self.clear()
            return
        if isinstance(self.cursor, clang.cindex.Cursor):
            if self.cursor == c:
                return
        self.cursorList = []
        self.cursor = c
        self.cursorText.config(state='normal')
        self.cursorText.delete('1.0', 'end')
        self._add_obj([c], self.foldTree.get_root())

        self.cursorText.config(state='disabled')
        self.goto_marker()


# Widget to show a position (Range and Location) in a source file.
class FileOutputFrame(ttk.Frame):
    def __init__(self, master=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self._create_widgets()
        self.fileName = None

    def _create_widgets(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.fileText = tk.Text(self, wrap='none')
        self.fileText.grid(row=0, sticky='nswe')
        self.fileText.tag_configure('range', background='gray')
        self.fileText.tag_configure('location', background='yellow')

        make_scrollable(self, self.fileText)

        self.fileText.config(state='disabled')

    def clear(self):
        self.fileText.config(state='normal')
        self.fileText.delete('1.0', 'end')
        self.fileText.config(state='disabled')
        self.fileName = None

    def set_location(self, srcRange, srcLocation):
        self.fileText.config(state='normal')
        self.fileText.tag_remove('range', '1.0', 'end')
        self.fileText.tag_remove('location', '1.0', 'end')

        newFileName = None
        if isinstance(srcRange, clang.cindex.SourceRange) and srcRange.start.file:
            newFileName = srcRange.start.file.name
        elif (isinstance(srcLocation, clang.cindex.SourceLocation) and
              srcLocation.file):
            newFileName = srcLocation.file.name
        else:
            self.fileText.delete('1.0', 'end')

        if newFileName and (self.fileName != newFileName):
            self.fileText.delete('1.0', 'end')
            data = []
            with open(newFileName, 'r') as f:
                data = f.read()
            self.fileText.insert('end', data)

        self.fileName = newFileName

        if isinstance(srcRange, clang.cindex.SourceRange):
            srcFrom =  '{0}.{1}'.format(srcRange.start.line, srcRange.start.column-1)
            srcTo =  '{0}.{1}'.format(srcRange.end.line, srcRange.end.column-1)
            self.fileText.tag_add('range', srcFrom, srcTo)
            self.fileText.see(srcTo)    # first scroll to the end
            self.fileText.see(srcFrom)  # then to the start, so usually all is shown

        if isinstance(srcLocation, clang.cindex.SourceLocation):
            if srcLocation.file:
                locFrom =  '{0}.{1}'.format(srcLocation.line, srcLocation.column-1)
                locTo =  '{0}.{1}'.format(srcLocation.line, srcLocation.column)
                self.fileText.tag_add('location', locFrom, locTo)
                self.fileText.see(locFrom)

        self.fileText.config(state='disabled')


# Widget to show the position of cursor or its token in source file
# This consists on a small toolbar to select kind of output (cursor or token)
# and the FileOutputFrame
class CursorFileOutputFrame(ttk.Frame):
    def __init__(self, master=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self.outState = tk.IntVar(value=0)
        self._create_widgets()
        self.cursor = None
        self.tokens = []
        self.tokenIdx = 0

    def _create_widgets(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='wne')
        toolbar.columnconfigure(5, weight=1)

        self.cursorBtn = ttk.Radiobutton(toolbar, text='Cursor', style='Toolbutton',
                variable=self.outState, value=0, command=self.change_out)
        self.cursorBtn.grid(row=0, column=0)

        self.tokensBtn = ttk.Radiobutton(toolbar, text='Tokens', style='Toolbutton',
                variable=self.outState, value=1, command=self.change_out)
        self.tokensBtn.grid(row=0, column=1)

        self.tokensPrevBtn = ttk.Button(toolbar, text='<', width=-3, style='Toolbutton',
                                            command=self.show_prev_token)
        self.tokensPrevBtn.grid(row=0, column=2)
        self.tokensLabel = ttk.Label(toolbar, text='-/-', width=-7, anchor='center')
        self.tokensLabel.grid(row=0, column=3)
        self.tokensNextBtn = ttk.Button(toolbar, text='>', width=-3, style='Toolbutton',
                                           command=self.show_next_token)
        self.tokensNextBtn.grid(row=0, column=4)

        self.tokenKind = ttk.Label(toolbar, text='')
        self.tokenKind.grid(row=0, column=5, sticky='we')

        self.fileOutputFrame = FileOutputFrame(self)

    def clear(self):
        self.fileOutputFrame.clear()
        self.outState.set(0)
        self.cursor = None
        self.tokens = []
        self.tokenIdx = 0
        self.tokensLabel.config(text='-/-')
        self.tokenKind.config(text='')
        self.cursorBtn.config(state='disabled')
        self.tokensBtn.config(state='disabled')
        self.tokensPrevBtn.config(state='disabled')
        self.tokensLabel.config(state='disabled')
        self.tokensNextBtn.config(state='disabled')

    def set_cursor(self, cursor):
        self.clear()
        if isinstance(cursor, clang.cindex.Cursor):
            self.cursor = cursor
            for token in cursor.get_tokens():
                self.tokens.append(token)
            self.tokenIdx = 0
            self.show_cursor()
            self.cursorBtn.config(state='normal')
            if len(self.tokens) > 0:
                self._show_label()
                self.tokensBtn.config(state='normal')
                self.tokensPrevBtn.config(state='normal')
                self.tokensLabel.config(state='normal')
                self.tokensNextBtn.config(state='normal')

    # New kind of output (Cursor pos/Token pos) selected.
    def change_out(self):
        if self.outState.get() == 0:
            self.show_cursor()
        else:
            self.show_token()

    def show_prev_token(self):
        self.tokenIdx-=1
        if self.tokenIdx < 0:
            self.tokenIdx = len(self.tokens)-1
        self.show_token()

    def show_next_token(self):
        self.tokenIdx+=1
        if self.tokenIdx >= len(self.tokens):
            self.tokenIdx = 0
        self.show_token()

    def show_cursor(self):
        self.outState.set(0)
        self.fileOutputFrame.set_location(self.cursor.extent, self.cursor.location)

    def _show_label(self):
        self.tokensLabel.config(text='{0}/{1}'.format(self.tokenIdx+1, len(self.tokens)))
        self.tokenKind.config(text=str(self.tokens[self.tokenIdx].kind))

    def show_token(self):
        self.outState.set(1)
        self._show_label()
        token = self.tokens[self.tokenIdx]
        self.fileOutputFrame.set_location(token.extent, token.location)


# Separate modal dialog window for search.
class SearchDialog(tk.Toplevel):

    _old_data = None    # remember last entered data

    def __init__(self, master=None):
        tk.Toplevel.__init__(self, master)
        self.transient(master)

        self.result = False             # True if [OK] pressed
        self.kindOptions = []
        for kind in clang.cindex.CursorKind.get_all_kinds():
            self.kindOptions.append(kind.name)
        self.kindOptions.sort()
        self.kindState = tk.IntVar(value=0)
        self.kindValue = tk.StringVar(value=self.kindOptions[0])
        self.searchtext = tk.StringVar(value='')
        self.caseInsensitive = tk.IntVar(value=0)
        self.useRegEx = tk.IntVar(value=0)

        if SearchDialog._old_data is not None:
            self.set_data(**SearchDialog._old_data)

        self.title('Search')
        self._create_widgets()
        self._on_check_kind()

        self.grab_set()

        self.bind('<Return>', self._on_ok)
        self.bind('<Escape>', self._on_cancel)

        self.protocol('WM_DELETE_WINDOW', self._on_cancel)

        self.wait_window(self)

    def _create_widgets(self):
        self.columnconfigure(0, weight=1)

        frame = ttk.Frame(self)
        frame.grid(row=0, column=0, sticky='nesw')
        frame.columnconfigure(1, weight=1)

        cb=ttk.Checkbutton(frame, text='Kind:', variable=self.kindState, command=self._on_check_kind)
        cb.grid(row=0, column=0)
        self.kindCBox = ttk.Combobox(frame, textvariable=self.kindValue, values=self.kindOptions)
        self.kindCBox.grid(row=0, column=1, sticky='we')

        label = tk.Label(frame, text='Spelling:')
        label.grid(row=1, column=0)
        searchEntry = ttk.Entry(frame, textvariable=self.searchtext, width=25)
        searchEntry.grid(row=1, column=1, sticky='we')

        cb=ttk.Checkbutton(frame, text='Ignore case', variable=self.caseInsensitive)
        cb.grid(row=2, column=1, sticky='w')
        cb=ttk.Checkbutton(frame, text='Use RegEx', variable=self.useRegEx)
        cb.grid(row=3, column=1, sticky='w')

        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky='e')

        btn = tk.Button(frame, text='OK', width=8, command=self._on_ok)
        btn.grid(row=0, column=0, sticky='e')

        btn = tk.Button(frame, text='Cancel', width=8, command=self._on_cancel)
        btn.grid(row=0, column=1, sticky='e')

    def get_data(self):
        data = {}
        data['use_CursorKind'] = self.kindState.get()
        data['CursorKind'] = self.kindValue.get()
        data['spelling'] = self.searchtext.get()
        data['caseInsensitive'] = self.caseInsensitive.get()
        data['use_RexEx'] = self.useRegEx.get()
        return data

    def set_data(self, **kwargs):
        self.kindState.set(kwargs['use_CursorKind'])
        self.kindValue.set(kwargs['CursorKind'])
        self.searchtext.set(kwargs['spelling'])
        self.caseInsensitive.set(kwargs['caseInsensitive'])
        self.useRegEx.set(kwargs['use_RexEx'])

    def _on_check_kind(self):
        if self.kindState.get():
            self.kindCBox.config(state='normal')
        else:
            self.kindCBox.config(state='disable')

    def _on_ok(self, event=None):
        self.result = True
        SearchDialog._old_data = self.get_data()
        self.destroy()

    def _on_cancel(self, event=None):
        self.destroy()


# Output frame shows the AST on the left (TreeView, ASTOutputFrame) and the selected Cursor on the right
# The right shows all member and the location of the cursor in source file.
# ASTOutputFrame on the left is the master for current selected cursor.
class OutputFrame(ttk.Frame):
    def __init__(self, master=None):
        ttk.Frame.__init__(self, master)
        self.grid(sticky='nswe')
        self.markerSetState = tk.IntVar(value=0) # after click [M#] Button 0: jump to marked cursor
                                                 #                         1: mark current cursor
        self._create_widgets()

        self.curIID = ''        # IID of current marked cursor in TreeView on the left
        self.curCursor = None
        self.history = []       # history of last visit cursors
        self.historyPos = -1    # current pos in this history, to walk in both directions
        self.searchResult = []
        self.searchPos = -1     # you can also walk through searchResult
        self.marker = []        # marked cursor using the [M#] Buttons
        for n in range(0, OutputFrame._MARKER_BTN_CNT): # list must have fixed size to check if there is
            self.marker.append(None)                    # a cursor at position x stored no not (None)
        self.clear()

    _MAX_HISTORY = 25
    _MARKER_BTN_CNT = 5

    def _create_widgets(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Toolbar start
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky='we')

        self.historyBackwardBtn = ttk.Button(toolbar, text='<', width=-3, style='Toolbutton',
                                            command=self.go_history_backward)
        self.historyBackwardBtn.grid(row=0, column=0)
        self.historyForwardBtn = ttk.Button(toolbar, text='>', width=-3, style='Toolbutton',
                                           command=self.go_history_forward)
        self.historyForwardBtn.grid(row=0, column=1)

        sep = ttk.Separator(toolbar, orient='vertical')
        sep.grid(row=0, column=2, sticky='ns', padx=5, pady=5)

        label = tk.Label(toolbar, text='Doubles:')
        label.grid(row=0, column=3)

        self.doublesBackwardBtn = ttk.Button(toolbar, text='<', width=-3, style='Toolbutton',
                                            command=self.go_doubles_backward)
        self.doublesBackwardBtn.grid(row=0, column=4)
        self.doublesLabel = ttk.Label(toolbar, text='-/-', width=-3, anchor='center')
        self.doublesLabel.grid(row=0, column=5)
        self.doublesForwardBtn = ttk.Button(toolbar, text='>', width=-3, style='Toolbutton',
                                           command=self.go_doubles_forward)
        self.doublesForwardBtn.grid(row=0, column=6)

        sep = ttk.Separator(toolbar, orient='vertical')
        sep.grid(row=0, column=7, sticky='ns', padx=5, pady=5)

        self.searchBtn = ttk.Button(toolbar, text='Search', style='Toolbutton',
                                   command=self._on_search)
        self.searchBtn.grid(row=0, column=8)
        self.searchBackwardBtn = ttk.Button(toolbar, text='<', width=-3, style='Toolbutton',
                                           command=self.go_search_backward)
        self.searchBackwardBtn.grid(row=0, column=9)
        self.serachLabel = ttk.Label(toolbar, text='-/-', width=-7, anchor='center')
        self.serachLabel.grid(row=0, column=10)
        self.searchForwardBtn = ttk.Button(toolbar, text='>', width=-3, style='Toolbutton',
                                          command=self.go_search_forward)
        self.searchForwardBtn.grid(row=0, column=11)

        sep = ttk.Separator(toolbar, orient='vertical')
        sep.grid(row=0, column=12, sticky='ns', padx=5, pady=5)

        self.markerSetBtn = ttk.Checkbutton(toolbar, text='MS', width=-4, style='Toolbutton',
                                            variable=self.markerSetState, onvalue=1, offvalue=0,
                                            command=self._on_marker_set)
        self.markerSetBtn.grid(row=0, column=13)

        self.markerBtns = []
        for n in range(0, OutputFrame._MARKER_BTN_CNT):
            btn = ttk.Button(toolbar, text='M{}'.format(n+1), width=-4, style='Toolbutton',
                             command=lambda n=n : self._on_marker_x(n))
            btn.grid(row=0, column=14+n)
            self.markerBtns.append(btn)
        # Toolbar end

        # ttk version of PanedWindow do not support all options
        pw1 = tk.PanedWindow(self, orient='horizontal')
        pw1.grid(row=1, column=0, sticky='nswe')

        self.astOutputFrame = ASTOutputFrame(pw1, selectCmd=self._on_cursor_selection)
        pw1.add(self.astOutputFrame, stretch='always')

        pw2 = tk.PanedWindow(pw1, orient='vertical')

        # remark ASTOutputFrame is the master for current selected cursor but you can click on a link
        # to other cursors in CursorOutputFrame, this must be forwarded to ASTOutputFrame.set_current_cursor
        self.cursorOutputFrame = CursorOutputFrame(pw2,
                                                   selectCmd=self.astOutputFrame.set_current_cursor)
        pw2.add(self.cursorOutputFrame, stretch='always')

        self.fileOutputFrame = CursorFileOutputFrame(pw2)
        pw2.add(self.fileOutputFrame, stretch='always')

        pw1.add(pw2, stretch='always')

    # There was a cursor selected at left ASTOutputFrame (TreeView on left).
    def _on_cursor_selection(self):
        curIID = self.astOutputFrame.get_current_iid()
        curCursor = self.astOutputFrame.get_current_cursor()
        if curIID != self.curIID: # do not update history if you currently walk through it
            self._set_active_cursor(curCursor)
            self._add_history(curIID)
            self.curIID = curIID
        self._update_doubles()
        self._update_search()

    # Set internal active cursor without updating history.
    # This is only called on cursor selection (via ASTOutputFrame) or history walk.
    def _set_active_cursor(self, cursor):
        self.curCursor = cursor
        self.cursorOutputFrame.set_cursor(cursor)
        self.fileOutputFrame.set_cursor(cursor)
        self.markerSetBtn.config(state='normal')

    def clear_history(self):
        self.history = []
        self.historyPos = -1
        self._update_history_buttons()

    def _add_history(self, iid):
        if self.historyPos < len(self.history):
            # we travel backward in time and change the history
            # so we change the time line and the future
            # therefore erase the old future
            self.history = self.history[:(self.historyPos+1)]
            # now the future is an empty sheet of paper

        if len(self.history) >= OutputFrame._MAX_HISTORY: # history to long?
            self.history = self.history[1:]
        else:
            self.historyPos = self.historyPos + 1

        self.history.append(iid)
        self._update_history_buttons()

    def go_history_backward(self):
        if self.historyPos > 0:
            self.historyPos = self.historyPos - 1
            self._update_history()
        self._update_history_buttons()

    def go_history_forward(self):
        if (self.historyPos+1) < len(self.history):
            self.historyPos = self.historyPos + 1
            self._update_history()
        self._update_history_buttons()

    # Switch to right cursor after walk through history.
    def _update_history(self):
        newIID = self.history[self.historyPos]
        self.curIID = newIID # set this before _on_cursor_selection() is called
        self.astOutputFrame.set_current_iid(newIID) # this will cause call of _on_cursor_selection()
        self._set_active_cursor(self.astOutputFrame.get_current_cursor())

    def _update_history_buttons(self):
        hLen = len(self.history)
        hPos = self.historyPos

        if hPos > 0: # we can go backward
            self.historyBackwardBtn.config(state='normal')
        else:
            self.historyBackwardBtn.config(state='disabled')

        if (hLen > 1) and ((hPos+1) < hLen): # we can go forward
            self.historyForwardBtn.config(state='normal')
        else:
            self.historyForwardBtn.config(state='disabled')

    def _clear_doubles(self):
        self.doublesForwardBtn.config(state='disabled')
        self.doublesLabel.config(state='disabled')
        self.doublesLabel.config(text='-/-')
        self.doublesBackwardBtn.config(state='disabled')

    def go_doubles_backward(self):
        iids = self.astOutputFrame.get_current_iids()
        if isinstance(iids, list):
            newIdx = (iids.index(self.curIID) - 1) % len(iids)
            newIID = iids[newIdx]
            self.astOutputFrame.set_current_iid(newIID)

    def go_doubles_forward(self):
        iids = self.astOutputFrame.get_current_iids()
        if isinstance(iids, list):
            newIdx = (iids.index(self.curIID) + 1) % len(iids)
            newIID = iids[newIdx]
            self.astOutputFrame.set_current_iid(newIID)

    # Update buttons states and label value for doubles (some cursors can be found several times in AST).
    def _update_doubles(self):
        iids = self.astOutputFrame.get_current_iids()
        if isinstance(iids, list):
            self.doublesForwardBtn.config(state='normal')
            self.doublesLabel.config(state='normal')
            self.doublesLabel.config(text='{0}/{1}'.format(iids.index(self.curIID)+1, len(iids)))
            self.doublesBackwardBtn.config(state='normal')
        else:
            self._clear_doubles()

    def clear_search(self):
        self.searchResult = []
        self._update_search()

    def _on_search(self):
        search = SearchDialog(self.winfo_toplevel())
        if search.result:
            data = search.get_data()
            self.searchResult = self.astOutputFrame.search(**data)
            self.searchPos = 0
            self._update_search()
            if len(self.searchResult) > 0:
                self.astOutputFrame.set_current_iid(self.searchResult[self.searchPos])

    def go_search_backward(self):
        self.searchPos = (self.searchPos - 1) % len(self.searchResult)
        self.astOutputFrame.set_current_iid(self.searchResult[self.searchPos])

    def go_search_forward(self):
        self.searchPos = (self.searchPos + 1) % len(self.searchResult)
        self.astOutputFrame.set_current_iid(self.searchResult[self.searchPos])

    # Update buttons states and label value for search.
    def _update_search(self):
        cnt = len(self.searchResult)
        if cnt > 0:
            serchIID = self.searchResult[self.searchPos]
            if self.curIID != serchIID:
                if self.curIID in self.searchResult:
                    self.searchPos = self.searchResult.index(self.curIID)
                    serchIID = self.curIID
            if self.curIID != serchIID:
                self.serachLabel.config(state='disabled')
            else:
                self.serachLabel.config(state='normal')
            self.searchForwardBtn.config(state='normal')
            self.serachLabel.config(text='{0}/{1}'.format(self.searchPos+1, cnt))
            self.searchBackwardBtn.config(state='normal')
        else:
            self.searchForwardBtn.config(state='disabled')
            self.serachLabel.config(state='disabled')
            self.serachLabel.config(text='-/-')
            self.searchBackwardBtn.config(state='disabled')

    # Update button states for marker.
    def _update_marker(self):
        for n in range(0, OutputFrame._MARKER_BTN_CNT):
            if self.marker[n] is not None:
                self.markerBtns[n].config(state='normal')
            else:
                self.markerBtns[n].config(state='disabled')

    # [MS] clicked
    def _on_marker_set(self):
        if self.markerSetState.get():
            for btn in self.markerBtns:
                btn.config(state='normal')
        else:
            self._update_marker()

    # [M#] clicked
    def _on_marker_x(self, num):
        if self.markerSetState.get():
            self.markerSetState.set(0)
            self.marker[num]=self.curCursor
            self._update_marker()
        else:
            self.astOutputFrame.set_current_cursor(self.marker[num])

    # Reset all outputs.
    def clear(self):
        self.curIID = ''
        self.clear_history()
        self._clear_doubles()
        self.clear_search()
        for n in range(0, OutputFrame._MARKER_BTN_CNT):
            self.marker[n] = None
        self.searchBtn.config(state='disabled')
        self.markerSetBtn.config(state='disabled')
        self._update_marker()
        self.astOutputFrame.clear()
        self.cursorOutputFrame.clear()
        self.fileOutputFrame.clear()

    def set_translationunit(self, tu):
        self.clear()
        self.astOutputFrame.set_translationunit(tu)
        self.searchBtn.config(state='normal')


# Main window combine all frames in tabs an contains glue logic between these frames
class Application(ttk.Frame):
    def __init__(self, options, master=None):
        ttk.Frame.__init__(self, master)
        self._set_style()
        self.grid(sticky='nswe')
        options.parse_cmd = self._on_parse
        self._create_widgets(options)

        self.index = clang.cindex.Index.create()

        if options.filename:
            self.inputFrame.load_filename(options.filename)
            if options.auto_parse:
                self._on_parse()
        else:
            self.inputFrame.set_filename('select file to parse =>')
            self.inputFrame.set_args(['-xc++',
                                      '-std=c++14',
                                      '-I/your/include/path',
                                      '-I/more/include/path'])


    def _create_widgets(self, options):
        top=self.winfo_toplevel()
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self)

        self.inputFrame = InputFrame(options, self.notebook)

        self.errorFrame = ErrorFrame(self.notebook)
        self.outputFrame = OutputFrame(self.notebook)

        self.notebook.add(self.inputFrame, text='Input')
        self.notebook.add(self.errorFrame, text='Errors')
        self.notebook.add(self.outputFrame, text='Output')
        self.notebook.grid(row=0, column=0, sticky='nswe')

        quitButton = ttk.Button(self, text='Quit',
            command=self.quit)
        quitButton.grid(row=1, column=0, sticky='we')

    def _set_style(self):
        s = ttk.Style()
        # center text in toolbuttons
        s.configure('Toolbutton', anchor='center', padding=s.lookup('TButton', 'padding'))

    # [parse] button is clicked
    def _on_parse(self):
        self.errorFrame.clear()
        self.outputFrame.clear()
        fileName = self.inputFrame.get_filename()
        args = self.inputFrame.get_args()
        tu = self.index.parse(
            fileName,
            args=args,
            options=InputFrame.get_parse_options(self.inputFrame.parseoptValue.get()))

        cntErr = self.errorFrame.set_errors(tu.diagnostics)
        self.outputFrame.set_translationunit(tu)

        if cntErr > 0:
            self.notebook.select(self.errorFrame)
        else:
            self.notebook.select(self.outputFrame)


def main():
    parser = argparse.ArgumentParser(description='Python Clang AST Viewer')
    parser.add_argument('-l', '--libfile', help='select Clang library file', nargs=1, dest='libFile')
    parser.add_argument('-p', '--auto-parse', help='automatically parse the input file', action='store_true', dest='auto_parse')
    parser.add_argument('-f', '--parse-options', dest='parse_options', default='Default',
                        help=f'specify parse options ({", ".join(InputFrame._PARSE_OPTIONS.keys())})')
    parser.add_argument('file', help='''Text file containing input data,
                        1st line = file to parse,
                        next lines = Clang arguments, one argument per line''',
                        nargs='?')
    args = parser.parse_args()

    if args.libFile:
        clang.cindex.Config.set_library_file(args.libFile[0])

    app = Application(AppOptions(
                        filename=args.file,
                        auto_parse=args.auto_parse,
                        parse_options=args.parse_options))

    app.master.title('PyClASVi')
    app.mainloop()

if __name__ == '__main__':
  main()
