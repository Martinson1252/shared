import sys
import re
import json
import base64
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit, 
                               QTextBrowser, QSplitter, QFileDialog, 
                               QMessageBox, QFontDialog, QMenu, QDialog,
                               QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QColorDialog, QGroupBox, QFormLayout, QToolBar,
                               QWidget, QTextEdit, QSpinBox, QTabWidget, QTabBar,
                               QLineEdit, QCheckBox, QKeySequenceEdit, QToolButton,
                               QWidgetAction)
from PySide6.QtCore import Qt, QTimer, QSettings, QRect, QSize, QUrl, Signal
from PySide6.QtGui import (QFont, QPalette, QColor, QAction, QTextCursor,
                           QPainter, QDesktopServices, QTextFormat, QKeySequence,
                           QTextDocument, QShortcut)


class LineNumberArea(QWidget):
    """Widget dla numerów wierszy"""
    
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.line_number_area_paint_event(event)


class CloseableTabBar(QTabBar):
    """TabBar z własnym przyciskiem zamknięcia 'x'"""
    
    close_tab_requested = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hover_close_index = -1
        self._is_dark_mode = False
        
    def set_dark_mode(self, is_dark):
        self._is_dark_mode = is_dark
        self.update()
        
    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.setWidth(size.width() + 24)  # Dodaj miejsce na "x"
        return size
    
    def mouseMoveEvent(self, event):
        old_hover = self._hover_close_index
        self._hover_close_index = -1
        
        for i in range(self.count()):
            if self._close_rect(i).contains(event.pos()):
                self._hover_close_index = i
                break
        
        if old_hover != self._hover_close_index:
            self.update()
        
        super().mouseMoveEvent(event)
    
    def leaveEvent(self, event):
        self._hover_close_index = -1
        self.update()
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            for i in range(self.count()):
                if self._close_rect(i).contains(event.pos()):
                    self.close_tab_requested.emit(i)
                    return
        
        super().mousePressEvent(event)
    
    def _close_rect(self, index):
        rect = self.tabRect(index)
        size = 16
        x = rect.right() - size - 6
        y = rect.center().y() - size // 2
        return QRect(x, y, size, size)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        for i in range(self.count()):
            close_rect = self._close_rect(i)
            
            if i == self._hover_close_index:
                # Czerwone tło przy hover
                painter.setBrush(QColor('#e81123'))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(close_rect, 3, 3)
                painter.setPen(QColor('white'))
            elif i == self.currentIndex():
                # Widoczny "x" na aktywnej karcie
                if self._is_dark_mode:
                    painter.setPen(QColor('#cccccc'))
                else:
                    painter.setPen(QColor('#555555'))
            else:
                # Blady "x" na nieaktywnych kartach
                if self._is_dark_mode:
                    painter.setPen(QColor('#666666'))
                else:
                    painter.setPen(QColor('#aaaaaa'))
            
            # Rysuj "×"
            font = painter.font()
            font.setPointSize(11)
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(close_rect, Qt.AlignCenter, "✕")


class CodeEditor(QPlainTextEdit):
    """Edytor kodu z numerami wierszy"""
    
    def __init__(self):
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        
        self.scroll_lines = 1
        
        # Domyślne skróty klawiszowe
        self.shortcut_move_up = QKeySequence("Alt+Up")
        self.shortcut_move_down = QKeySequence("Alt+Down")
        self.shortcut_duplicate = QKeySequence("Ctrl+D")
        
        self.line_number_bg_color = QColor('#e8e8e8')
        self.line_number_text_color = QColor('#666666')
        self.current_line_bg_color = QColor('#fffacd')
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
    
    def set_shortcuts(self, move_up, move_down, duplicate):
        """Ustaw skróty klawiszowe"""
        self.shortcut_move_up = QKeySequence(move_up)
        self.shortcut_move_down = QKeySequence(move_down)
        self.shortcut_duplicate = QKeySequence(duplicate)
    
    def set_scroll_lines(self, lines):
        self.scroll_lines = max(1, lines)
    
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        scrollbar = self.verticalScrollBar()
        
        if delta > 0:
            scrollbar.setValue(scrollbar.value() - self.scroll_lines)
        elif delta < 0:
            scrollbar.setValue(scrollbar.value() + self.scroll_lines)
        
        event.accept()
    
    def keyPressEvent(self, event):
        """Obsługa skrótów klawiszowych"""
        key_seq = QKeySequence(event.keyCombination())
        
        # Duplikuj linię/zaznaczenie
        if key_seq.matches(self.shortcut_duplicate) == QKeySequence.ExactMatch:
            self.duplicate_line_or_selection()
            return
        
        # Przesuń linie w górę (Alt+Up)
        if key_seq.matches(self.shortcut_move_up) == QKeySequence.ExactMatch:
            self.move_lines_up()
            return
        
        # Przesuń linie w dół (Alt+Down)
        if key_seq.matches(self.shortcut_move_down) == QKeySequence.ExactMatch:
            self.move_lines_down()
            return
        
        super().keyPressEvent(event)
    
    def duplicate_line_or_selection(self):
        """Duplikuj zaznaczony tekst lub bieżącą linię"""
        cursor = self.textCursor()
        
        if cursor.hasSelection():
            # Duplikuj zaznaczony tekst
            selected_text = cursor.selectedText()
            selected_text = selected_text.replace('\u2029', '\n')
            pos = cursor.selectionEnd()
            cursor.setPosition(pos)
            
            # Dodaj nową linię jeśli włączone w ustawieniach
            if hasattr(self, 'duplicate_with_newline') and self.duplicate_with_newline:
                cursor.insertText('\n' + selected_text)
            else:
                cursor.insertText(selected_text)
        else:
            # Duplikuj bieżącą linię
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            line_text = cursor.selectedText()
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + line_text)
        
        self.setTextCursor(cursor)
    
    def get_selected_lines_range(self):
        """Pobierz zakres linii objętych zaznaczeniem (wszystkie dotknięte linie)"""
        cursor = self.textCursor()
        
        if cursor.hasSelection():
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()
            
            # Znajdź numer bloku dla początku zaznaczenia
            cursor.setPosition(start_pos)
            start_block = cursor.blockNumber()
            
            # Znajdź numer bloku dla końca zaznaczenia
            cursor.setPosition(end_pos)
            end_block = cursor.blockNumber()
            
            return start_block, end_block
        else:
            return cursor.blockNumber(), cursor.blockNumber()
    
    def move_lines_up(self):
        """Przesuń zaznaczone linie (lub bieżącą linię) w górę o 1"""
        start_block, end_block = self.get_selected_lines_range()
        
        if start_block == 0:
            return  # Już na początku
        
        doc = self.document()
        cursor = self.textCursor()
        
        # Zapamiętaj czy było zaznaczenie
        had_selection = cursor.hasSelection()
        
        cursor.beginEditBlock()
        
        # Pobierz tekst linii powyżej (ta która będzie przesunięta w dół)
        prev_block = doc.findBlockByNumber(start_block - 1)
        prev_text = prev_block.text()
        
        # Pobierz tekst wszystkich linii do przesunięcia
        lines_to_move = []
        for i in range(start_block, end_block + 1):
            block = doc.findBlockByNumber(i)
            lines_to_move.append(block.text())
        
        # Zaznacz od początku linii powyżej do końca ostatniej linii do przesunięcia
        cursor.setPosition(prev_block.position())
        end_block_obj = doc.findBlockByNumber(end_block)
        cursor.setPosition(end_block_obj.position() + end_block_obj.length() - 1, QTextCursor.KeepAnchor)
        
        # Zamień tekst: najpierw linie do przesunięcia, potem linia która była powyżej
        new_text = '\n'.join(lines_to_move) + '\n' + prev_text
        cursor.insertText(new_text)
        
        # Ustaw kursor/zaznaczenie na nowej pozycji
        new_start_block = doc.findBlockByNumber(start_block - 1)
        new_end_block = doc.findBlockByNumber(end_block - 1)
        
        if had_selection:
            cursor.setPosition(new_start_block.position())
            cursor.setPosition(new_end_block.position() + new_end_block.length() - 1, QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(new_start_block.position())
        
        cursor.endEditBlock()
        self.setTextCursor(cursor)
    
    def move_lines_down(self):
        """Przesuń zaznaczone linie (lub bieżącą linię) w dół o 1"""
        start_block, end_block = self.get_selected_lines_range()
        
        if end_block >= self.blockCount() - 1:
            return  # Już na końcu
        
        doc = self.document()
        cursor = self.textCursor()
        
        # Zapamiętaj czy było zaznaczenie
        had_selection = cursor.hasSelection()
        
        cursor.beginEditBlock()
        
        # Pobierz tekst linii poniżej (ta która będzie przesunięta w górę)
        next_block = doc.findBlockByNumber(end_block + 1)
        next_text = next_block.text()
        
        # Pobierz tekst wszystkich linii do przesunięcia
        lines_to_move = []
        for i in range(start_block, end_block + 1):
            block = doc.findBlockByNumber(i)
            lines_to_move.append(block.text())
        
        # Zaznacz od początku pierwszej linii do końca linii poniżej
        first_block = doc.findBlockByNumber(start_block)
        cursor.setPosition(first_block.position())
        cursor.setPosition(next_block.position() + next_block.length() - 1, QTextCursor.KeepAnchor)
        
        # Zamień tekst: najpierw linia która była poniżej, potem linie do przesunięcia
        new_text = next_text + '\n' + '\n'.join(lines_to_move)
        cursor.insertText(new_text)
        
        # Ustaw kursor/zaznaczenie na nowej pozycji
        new_start_block = doc.findBlockByNumber(start_block + 1)
        new_end_block = doc.findBlockByNumber(end_block + 1)
        
        if had_selection:
            cursor.setPosition(new_start_block.position())
            cursor.setPosition(new_end_block.position() + new_end_block.length() - 1, QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(new_start_block.position())
        
        cursor.endEditBlock()
        self.setTextCursor(cursor)
    
    # Stare metody dla kompatybilności
    def duplicate_line(self):
        self.duplicate_line_or_selection()
    
    def move_line_up(self):
        self.move_lines_up()
    
    def move_line_down(self):
        self.move_lines_down()
        
    def set_dark_mode(self, is_dark):
        if is_dark:
            self.line_number_bg_color = QColor('#2d2d2d')
            self.line_number_text_color = QColor('#858585')
            self.current_line_bg_color = QColor('#3a3a3a')
        else:
            self.line_number_bg_color = QColor('#e8e8e8')
            self.line_number_text_color = QColor('#666666')
            self.current_line_bg_color = QColor('#fffacd')
        self.line_number_area.update()
        self.highlight_current_line()
        
    def line_number_area_width(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits + 10
        return space
    
    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    
    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), 
                                                 self.line_number_area_width(), cr.height()))
    
    def highlight_current_line(self):
        extra_selections = []
        
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(self.current_line_bg_color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        
        self.setExtraSelections(extra_selections)
    
    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.line_number_bg_color)
        
        painter.setPen(QColor('#cccccc') if self.line_number_bg_color.lightness() > 128 else QColor('#404040'))
        painter.drawLine(self.line_number_area.width() - 1, event.rect().top(),
                        self.line_number_area.width() - 1, event.rect().bottom())
        
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        
        current_block_number = self.textCursor().blockNumber()
        
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                
                if block_number == current_block_number:
                    painter.setPen(QColor('#000000') if self.line_number_bg_color.lightness() > 128 else QColor('#ffffff'))
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    painter.setPen(self.line_number_text_color)
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                    
                painter.drawText(0, top, self.line_number_area.width() - 8, 
                               self.fontMetrics().height(),
                               Qt.AlignRight | Qt.AlignVCenter, number)
            
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class FindReplaceDialog(QDialog):
    """Dialog wyszukiwania i zamiany"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Znajdź i zamień")
        self.setFixedWidth(450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("Znajdź:"))
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Wpisz szukany tekst...")
        find_layout.addWidget(self.find_input)
        layout.addLayout(find_layout)
        
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("Zamień na:"))
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Wpisz tekst zastępczy...")
        replace_layout.addWidget(self.replace_input)
        layout.addLayout(replace_layout)
        
        options_layout = QHBoxLayout()
        self.case_sensitive = QCheckBox("Rozróżniaj wielkość liter")
        self.whole_words = QCheckBox("Całe słowa")
        options_layout.addWidget(self.case_sensitive)
        options_layout.addWidget(self.whole_words)
        options_layout.addStretch()
        layout.addLayout(options_layout)
        
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.result_label)
        
        button_layout = QHBoxLayout()
        
        find_next_btn = QPushButton("Znajdź następny")
        find_next_btn.clicked.connect(self.find_next)
        button_layout.addWidget(find_next_btn)
        
        find_prev_btn = QPushButton("Znajdź poprzedni")
        find_prev_btn.clicked.connect(self.find_previous)
        button_layout.addWidget(find_prev_btn)
        
        replace_btn = QPushButton("Zamień")
        replace_btn.clicked.connect(self.replace)
        button_layout.addWidget(replace_btn)
        
        replace_all_btn = QPushButton("Zamień wszystko")
        replace_all_btn.clicked.connect(self.replace_all)
        button_layout.addWidget(replace_all_btn)
        
        layout.addLayout(button_layout)
        
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Zamknij")
        close_btn.clicked.connect(self.close)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)
        
        self.setLayout(layout)
        self.find_input.returnPressed.connect(self.find_next)
    
    def set_editor(self, editor):
        self.editor = editor
    
    def get_find_flags(self):
        flags = QTextDocument.FindFlags()
        if self.case_sensitive.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.whole_words.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags
    
    def find_next(self):
        if not self.editor or not self.find_input.text():
            return
        
        text = self.find_input.text()
        flags = self.get_find_flags()
        
        found = self.editor.find(text, flags)
        
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(text, flags)
        
        if found:
            self.result_label.setText("Znaleziono")
            self.result_label.setStyleSheet("color: green; font-style: italic;")
        else:
            self.result_label.setText("Nie znaleziono")
            self.result_label.setStyleSheet("color: red; font-style: italic;")
    
    def find_previous(self):
        if not self.editor or not self.find_input.text():
            return
        
        text = self.find_input.text()
        flags = self.get_find_flags() | QTextDocument.FindBackward
        
        found = self.editor.find(text, flags)
        
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(text, flags)
        
        if found:
            self.result_label.setText("Znaleziono")
            self.result_label.setStyleSheet("color: green; font-style: italic;")
        else:
            self.result_label.setText("Nie znaleziono")
            self.result_label.setStyleSheet("color: red; font-style: italic;")
    
    def replace(self):
        if not self.editor:
            return
        
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self.replace_input.text())
        
        self.find_next()
    
    def replace_all(self):
        if not self.editor or not self.find_input.text():
            return
        
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.editor.setTextCursor(cursor)
        
        count = 0
        flags = self.get_find_flags()
        
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        
        while self.editor.find(find_text, flags):
            tc = self.editor.textCursor()
            tc.insertText(replace_text)
            count += 1
        
        cursor.endEditBlock()
        
        self.result_label.setText(f"Zamieniono {count} wystąpień")
        self.result_label.setStyleSheet("color: blue; font-style: italic;")


class ShortcutSettingsDialog(QDialog):
    """Dialog do ustawień skrótów klawiszowych"""
    
    def __init__(self, shortcuts, parent=None):
        super().__init__(parent)
        self.shortcuts = shortcuts.copy()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Ustawienia skrótów klawiszowych")
        self.setFixedWidth(450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        
        desc_label = QLabel("Kliknij w pole i naciśnij nową kombinację klawiszy:")
        layout.addWidget(desc_label)
        
        form_layout = QFormLayout()
        
        self.shortcut_edits = {}
        
        shortcuts_info = [
            ('move_up', 'Przesuń linię w górę:'),
            ('move_down', 'Przesuń linię w dół:'),
            ('duplicate', 'Duplikuj linię/zaznaczenie:'),
        ]
        
        for key, label in shortcuts_info:
            edit = QKeySequenceEdit()
            edit.setKeySequence(QKeySequence(self.shortcuts.get(key, '')))
            self.shortcut_edits[key] = edit
            form_layout.addRow(label, edit)
        
        layout.addLayout(form_layout)
        
        hint_label = QLabel("💡 Domyślne: Alt+↑/↓ dla przesuwania, Ctrl+D dla duplikacji")
        hint_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint_label)
        
        layout.addSpacing(10)
        
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Przywróć domyślne")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def reset_to_defaults(self):
        defaults = {
            'move_up': 'Alt+Up',
            'move_down': 'Alt+Down',
            'duplicate': 'Ctrl+D'
        }
        for key, edit in self.shortcut_edits.items():
            edit.setKeySequence(QKeySequence(defaults.get(key, '')))
    
    def get_shortcuts(self):
        return {key: edit.keySequence().toString() 
                for key, edit in self.shortcut_edits.items()}


class EditorTab(QWidget):
    """Widget pojedynczej karty edytora"""
    
    content_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.view_mode = 1
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.splitter = QSplitter(Qt.Horizontal)
        
        self.text_edit = CodeEditor()
        self.text_edit.setFont(QFont('Consolas', 11))
        self.text_edit.setTabStopDistance(40)
        
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setOpenLinks(False)
        
        self.splitter.addWidget(self.text_edit)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([600, 600])
        
        layout.addWidget(self.splitter)
        
        self.text_edit.textChanged.connect(self.content_changed.emit)
    
    def set_view_mode(self, mode):
        self.view_mode = mode
        
        if mode == 0:
            self.text_edit.show()
            self.preview.hide()
        elif mode == 1:
            self.text_edit.show()
            self.preview.show()
            self.splitter.setSizes([600, 600])
        elif mode == 2:
            self.text_edit.hide()
            self.preview.show()
    
    def get_content(self):
        return self.text_edit.toPlainText()
    
    def set_content(self, content):
        self.text_edit.setPlainText(content)
    
    def is_modified(self):
        return self.text_edit.document().isModified()
    
    def set_modified(self, modified):
        self.text_edit.document().setModified(modified)


class ColorScheme:
    """Schemat kolorów dla aplikacji"""
    
    def __init__(self):
        self.light = {
            'window': '#f0f0f0',
            'text': '#000000',
            'base': '#ffffff',
            'button': '#e0e0e0',
            'highlight': '#308cc6',
            # Ogólne MD
            'md_bg': '#ffffff',
            'md_text': '#2c3e50',
            'md_border': '#3498db',
            # Nagłówki H1
            'md_h1_color': '#1a5276',
            'md_h1_bg': 'transparent',
            'md_h1_size': '40',
            'md_h1_font': 'inherit',
            # Nagłówki H2
            'md_h2_color': '#1e8449',
            'md_h2_bg': 'transparent',
            'md_h2_size': '24',
            'md_h2_font': 'inherit',
            # Nagłówki H3
            'md_h3_color': '#7d3c98',
            'md_h3_bg': 'transparent',
            'md_h3_size': '20',
            'md_h3_font': 'inherit',
            # Nagłówki H4
            'md_h4_color': '#b8860b',
            'md_h4_bg': 'transparent',
            'md_h4_size': '18',
            'md_h4_font': 'inherit',
            # Nagłówki H5
            'md_h5_color': '#2e8b57',
            'md_h5_bg': 'transparent',
            'md_h5_size': '16',
            'md_h5_font': 'inherit',
            # Nagłówki H6
            'md_h6_color': '#4682b4',
            'md_h6_bg': 'transparent',
            'md_h6_size': '14',
            'md_h6_font': 'inherit',
            # Kod inline
            'md_code_bg': '#f4f4f4',
            'md_code_text': '#c0392b',
            'md_code_size': '14',
            'md_code_font': 'Consolas, monospace',
            # Blok kodu
            'md_pre_bg': '#2d2d2d',
            'md_pre_text': '#f0f0f0',
            'md_pre_size': '14',
            'md_pre_font': 'Consolas, monospace',
            'md_pre_padding': '16',
            # Cytat
            'md_quote_bg': '#f0f8ff',
            'md_quote_text': '#555555',
            'md_quote_border': '#3498db',
            'md_quote_size': '16',
            'md_quote_font': 'Georgia, serif',
            'md_quote_bar_width': '4',
            'md_quote_italic': 'true',
            # Link
            'md_link': '#3498db',
            'md_link_hover': '#2980b9',
            'md_link_bg': 'transparent',
            'md_link_size': '16',
            'md_link_font': 'inherit',
            # Tabela
            'md_table_text': '#2c3e50',
            'md_table_bg': '#f8f9fa',
            'md_table_border': '#dddddd',
            'md_table_header_bg': '#3498db',
            'md_table_header_text': '#ffffff',
            'md_table_size': '14',
            'md_table_font': 'inherit',
            # Lista nieuporządkowana
            'md_ul_color': '#2c3e50',
            'md_ul_bg': 'transparent',
            'md_ul_marker': '#3498db',
            'md_ul_size': '16',
            'md_ul_font': 'inherit',
            # Lista numerowana
            'md_ol_color': '#2c3e50',
            'md_ol_bg': 'transparent',
            'md_ol_marker': '#e74c3c',
            'md_ol_size': '16',
            'md_ol_font': 'inherit',
            # Linia pozioma
            'md_hr_color': '#cccccc',
            'md_hr_height': '2',
            # Opcje linków
            'md_link_underline': 'false',
            # Odstęp między liniami
            'md_line_height': '1.6'
        }
        
        self.dark = {
            'window': '#1e1e1e',
            'text': '#d4d4d4',
            'base': '#252525',
            'button': '#2d2d2d',
            'highlight': '#2a82da',
            # Ogólne MD
            'md_bg': '#1e1e1e',
            'md_text': '#d4d4d4',
            'md_border': '#569cd6',
            # Nagłówki H1
            'md_h1_color': '#4ec9b0',
            'md_h1_bg': 'transparent',
            'md_h1_size': '40',
            'md_h1_font': 'inherit',
            # Nagłówki H2
            'md_h2_color': '#9cdcfe',
            'md_h2_bg': 'transparent',
            'md_h2_size': '24',
            'md_h2_font': 'inherit',
            # Nagłówki H3
            'md_h3_color': '#c586c0',
            'md_h3_bg': 'transparent',
            'md_h3_size': '20',
            'md_h3_font': 'inherit',
            # Nagłówki H4
            'md_h4_color': '#dcdcaa',
            'md_h4_bg': 'transparent',
            'md_h4_size': '18',
            'md_h4_font': 'inherit',
            # Nagłówki H5
            'md_h5_color': '#4ec9b0',
            'md_h5_bg': 'transparent',
            'md_h5_size': '16',
            'md_h5_font': 'inherit',
            # Nagłówki H6
            'md_h6_color': '#569cd6',
            'md_h6_bg': 'transparent',
            'md_h6_size': '14',
            'md_h6_font': 'inherit',
            # Kod inline
            'md_code_bg': '#3a3a3a',
            'md_code_text': '#ce9178',
            'md_code_size': '14',
            'md_code_font': 'Consolas, monospace',
            # Blok kodu
            'md_pre_bg': '#0d0d0d',
            'md_pre_text': '#e0e0e0',
            'md_pre_size': '14',
            'md_pre_font': 'Consolas, monospace',
            'md_pre_padding': '16',
            # Cytat
            'md_quote_bg': '#2a3a4a',
            'md_quote_text': '#9cdcfe',
            'md_quote_border': '#569cd6',
            'md_quote_size': '16',
            'md_quote_font': 'Georgia, serif',
            'md_quote_bar_width': '4',
            'md_quote_italic': 'true',
            # Link
            'md_link': '#569cd6',
            'md_link_hover': '#9cdcfe',
            'md_link_bg': 'transparent',
            'md_link_size': '16',
            'md_link_font': 'inherit',
            # Tabela
            'md_table_text': '#d4d4d4',
            'md_table_bg': '#2d2d2d',
            'md_table_border': '#404040',
            'md_table_header_bg': '#569cd6',
            'md_table_header_text': '#ffffff',
            'md_table_size': '14',
            'md_table_font': 'inherit',
            # Lista nieuporządkowana
            'md_ul_color': '#d4d4d4',
            'md_ul_bg': 'transparent',
            'md_ul_marker': '#569cd6',
            'md_ul_size': '16',
            'md_ul_font': 'inherit',
            # Lista numerowana
            'md_ol_color': '#d4d4d4',
            'md_ol_bg': 'transparent',
            'md_ol_marker': '#ce9178',
            'md_ol_size': '16',
            'md_ol_font': 'inherit',
            # Linia pozioma
            'md_hr_color': '#404040',
            'md_hr_height': '2',
            # Opcje linków
            'md_link_underline': 'false',
            # Odstęp między liniami
            'md_line_height': '1.6'
        }


class ScrollSettingsDialog(QDialog):
    """Dialog do ustawień przewijania"""
    
    def __init__(self, current_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ustawienia przewijania")
        self.setFixedWidth(350)
        
        layout = QVBoxLayout()
        
        desc_label = QLabel("Ustaw liczbę linii przewijanych przy jednym ruchu kółka myszy:")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Liczba linii:"))
        
        self.spin_box = QSpinBox()
        self.spin_box.setMinimum(1)
        self.spin_box.setMaximum(20)
        self.spin_box.setValue(current_lines)
        self.spin_box.setFixedWidth(80)
        input_layout.addWidget(self.spin_box)
        input_layout.addStretch()
        
        layout.addLayout(input_layout)
        
        hint_label = QLabel("💡 Wartość 1 = przewijanie po jednej linii\n     Wartość 3 = standardowe przewijanie systemu")
        hint_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint_label)
        
        layout.addSpacing(10)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_scroll_lines(self):
        return self.spin_box.value()


class MarkdownStyleDialog(QDialog):
    """Dialog do personalizacji stylów Markdown"""
    
    def __init__(self, colors, mode, parent=None):
        super().__init__(parent)
        self.colors = colors.copy()
        self.mode = mode
        self.md_font_family = "system-ui"
        self.md_font_size = 16
        self.color_buttons = {}
        self.font_inputs = {}
        self.size_inputs = {}
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(f"Style podglądu Markdown - Motyw {'ciemny' if self.mode == 'dark' else 'jasny'}")
        self.setMinimumWidth(700)
        self.setMinimumHeight(650)
        
        main_layout = QVBoxLayout()
        
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        
        # === Ogólne ===
        general_group = QGroupBox("Ogólne ustawienia dokumentu")
        general_layout = QFormLayout()
        
        self.font_family_combo = QLineEdit(self.md_font_family)
        self.font_family_combo.setPlaceholderText("system-ui, Arial, sans-serif")
        general_layout.addRow("Główna czcionka:", self.font_family_combo)
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setMinimum(8)
        self.font_size_spin.setMaximum(32)
        self.font_size_spin.setValue(self.md_font_size)
        self.font_size_spin.setSuffix(" px")
        general_layout.addRow("Rozmiar podstawowy:", self.font_size_spin)
        
        from PySide6.QtWidgets import QDoubleSpinBox
        self.line_height_spin = QDoubleSpinBox()
        self.line_height_spin.setMinimum(1.0)
        self.line_height_spin.setMaximum(3.0)
        self.line_height_spin.setSingleStep(0.1)
        self.line_height_spin.setValue(float(self.colors.get('md_line_height', '1')))
        general_layout.addRow("Odstęp między liniami:", self.line_height_spin)
        
        self._add_color_row(general_layout, 'md_bg', 'Tło dokumentu')
        self._add_color_row(general_layout, 'md_text', 'Kolor tekstu')
        self._add_color_row(general_layout, 'md_border', 'Kolor obramowań')
        
        general_group.setLayout(general_layout)
        layout.addWidget(general_group)
        
        # === Nagłówek H1 ===
        h1_group = QGroupBox("Nagłówek H1")
        h1_layout = QFormLayout()
        self._add_color_row(h1_layout, 'md_h1_color', 'Kolor tekstu')
        self._add_color_row(h1_layout, 'md_h1_bg', 'Kolor tła')
        self._add_font_row(h1_layout, 'md_h1_font', 'Czcionka')
        self._add_size_row(h1_layout, 'md_h1_size', 'Rozmiar')
        h1_group.setLayout(h1_layout)
        layout.addWidget(h1_group)
        
        # === Nagłówek H2 ===
        h2_group = QGroupBox("Nagłówek H2")
        h2_layout = QFormLayout()
        self._add_color_row(h2_layout, 'md_h2_color', 'Kolor tekstu')
        self._add_color_row(h2_layout, 'md_h2_bg', 'Kolor tła')
        self._add_font_row(h2_layout, 'md_h2_font', 'Czcionka')
        self._add_size_row(h2_layout, 'md_h2_size', 'Rozmiar')
        h2_group.setLayout(h2_layout)
        layout.addWidget(h2_group)
        
        # === Nagłówek H3 ===
        h3_group = QGroupBox("Nagłówek H3")
        h3_layout = QFormLayout()
        self._add_color_row(h3_layout, 'md_h3_color', 'Kolor tekstu')
        self._add_color_row(h3_layout, 'md_h3_bg', 'Kolor tła')
        self._add_font_row(h3_layout, 'md_h3_font', 'Czcionka')
        self._add_size_row(h3_layout, 'md_h3_size', 'Rozmiar')
        h3_group.setLayout(h3_layout)
        layout.addWidget(h3_group)
        
        # === Nagłówek H4 ===
        h4_group = QGroupBox("Nagłówek H4")
        h4_layout = QFormLayout()
        self._add_color_row(h4_layout, 'md_h4_color', 'Kolor tekstu')
        self._add_color_row(h4_layout, 'md_h4_bg', 'Kolor tła')
        self._add_font_row(h4_layout, 'md_h4_font', 'Czcionka')
        self._add_size_row(h4_layout, 'md_h4_size', 'Rozmiar')
        h4_group.setLayout(h4_layout)
        layout.addWidget(h4_group)
        
        # === Nagłówek H5 ===
        h5_group = QGroupBox("Nagłówek H5")
        h5_layout = QFormLayout()
        self._add_color_row(h5_layout, 'md_h5_color', 'Kolor tekstu')
        self._add_color_row(h5_layout, 'md_h5_bg', 'Kolor tła')
        self._add_font_row(h5_layout, 'md_h5_font', 'Czcionka')
        self._add_size_row(h5_layout, 'md_h5_size', 'Rozmiar')
        h5_group.setLayout(h5_layout)
        layout.addWidget(h5_group)
        
        # === Nagłówek H6 ===
        h6_group = QGroupBox("Nagłówek H6")
        h6_layout = QFormLayout()
        self._add_color_row(h6_layout, 'md_h6_color', 'Kolor tekstu')
        self._add_color_row(h6_layout, 'md_h6_bg', 'Kolor tła')
        self._add_font_row(h6_layout, 'md_h6_font', 'Czcionka')
        self._add_size_row(h6_layout, 'md_h6_size', 'Rozmiar')
        h6_group.setLayout(h6_layout)
        layout.addWidget(h6_group)
        
        # === Kod inline ===
        code_group = QGroupBox("Kod inline (`kod`)")
        code_layout = QFormLayout()
        self._add_color_row(code_layout, 'md_code_text', 'Kolor tekstu')
        self._add_color_row(code_layout, 'md_code_bg', 'Kolor tła')
        self._add_font_row(code_layout, 'md_code_font', 'Czcionka')
        self._add_size_row(code_layout, 'md_code_size', 'Rozmiar')
        code_group.setLayout(code_layout)
        layout.addWidget(code_group)
        
        # === Blok kodu ===
        pre_group = QGroupBox("Blok kodu (```kod```)")
        pre_layout = QFormLayout()
        self._add_color_row(pre_layout, 'md_pre_text', 'Kolor tekstu')
        self._add_color_row(pre_layout, 'md_pre_bg', 'Kolor tła')
        self._add_font_row(pre_layout, 'md_pre_font', 'Czcionka')
        self._add_size_row(pre_layout, 'md_pre_size', 'Rozmiar')
        
        # Padding dla bloku kodu
        self.pre_padding_spin = QSpinBox()
        self.pre_padding_spin.setMinimum(0)
        self.pre_padding_spin.setMaximum(50)
        self.pre_padding_spin.setValue(int(self.colors.get('md_pre_padding', '16')))
        self.pre_padding_spin.setSuffix(" px")
        pre_layout.addRow("Padding:", self.pre_padding_spin)
        
        pre_group.setLayout(pre_layout)
        layout.addWidget(pre_group)
        
        # === Cytat ===
        quote_group = QGroupBox("Cytat (> cytat) - styl Discord")
        quote_layout = QFormLayout()
        self._add_color_row(quote_layout, 'md_quote_text', 'Kolor tekstu')
        self._add_color_row(quote_layout, 'md_quote_bg', 'Kolor tła')
        self._add_color_row(quote_layout, 'md_quote_border', 'Kolor paska')
        self._add_font_row(quote_layout, 'md_quote_font', 'Czcionka')
        self._add_size_row(quote_layout, 'md_quote_size', 'Rozmiar tekstu')
        
        # Grubość paska
        self.quote_bar_width_spin = QSpinBox()
        self.quote_bar_width_spin.setMinimum(1)
        self.quote_bar_width_spin.setMaximum(20)
        self.quote_bar_width_spin.setValue(int(self.colors.get('md_quote_bar_width', '4')))
        self.quote_bar_width_spin.setSuffix(" px")
        quote_layout.addRow("Grubość paska:", self.quote_bar_width_spin)
        
        # Kursywa
        self.quote_italic_check = QCheckBox()
        self.quote_italic_check.setChecked(self.colors.get('md_quote_italic', 'true') == 'true')
        quote_layout.addRow("Kursywa:", self.quote_italic_check)
        
        quote_group.setLayout(quote_layout)
        layout.addWidget(quote_group)
        
        # === Link ===
        link_group = QGroupBox("Hiperłącze [tekst](url)")
        link_layout = QFormLayout()
        self._add_color_row(link_layout, 'md_link', 'Kolor linku')
        self._add_color_row(link_layout, 'md_link_hover', 'Kolor po najechaniu')
        self._add_color_row(link_layout, 'md_link_bg', 'Kolor tła')
        self._add_font_row(link_layout, 'md_link_font', 'Czcionka')
        self._add_size_row(link_layout, 'md_link_size', 'Rozmiar')
        
        self.link_underline_check = QCheckBox()
        self.link_underline_check.setChecked(self.colors.get('md_link_underline', 'false') == 'true')
        link_layout.addRow("Podkreślenie:", self.link_underline_check)
        
        link_group.setLayout(link_layout)
        layout.addWidget(link_group)
        
        # === Tabela ===
        table_group = QGroupBox("Tabela")
        table_layout = QFormLayout()
        self._add_color_row(table_layout, 'md_table_text', 'Kolor tekstu')
        self._add_color_row(table_layout, 'md_table_bg', 'Tło wierszy')
        self._add_color_row(table_layout, 'md_table_border', 'Kolor obramowania')
        self._add_color_row(table_layout, 'md_table_header_bg', 'Tło nagłówka')
        self._add_color_row(table_layout, 'md_table_header_text', 'Tekst nagłówka')
        self._add_font_row(table_layout, 'md_table_font', 'Czcionka')
        self._add_size_row(table_layout, 'md_table_size', 'Rozmiar')
        table_group.setLayout(table_layout)
        layout.addWidget(table_group)
        
        # === Lista nieuporządkowana ===
        ul_group = QGroupBox("Lista nieuporządkowana (• punkt)")
        ul_layout = QFormLayout()
        self._add_color_row(ul_layout, 'md_ul_color', 'Kolor tekstu')
        self._add_color_row(ul_layout, 'md_ul_bg', 'Kolor tła')
        self._add_color_row(ul_layout, 'md_ul_marker', 'Kolor znacznika •')
        self._add_font_row(ul_layout, 'md_ul_font', 'Czcionka')
        self._add_size_row(ul_layout, 'md_ul_size', 'Rozmiar')
        ul_group.setLayout(ul_layout)
        layout.addWidget(ul_group)
        
        # === Lista numerowana ===
        ol_group = QGroupBox("Lista numerowana (1. 2. 3.)")
        ol_layout = QFormLayout()
        self._add_color_row(ol_layout, 'md_ol_color', 'Kolor tekstu')
        self._add_color_row(ol_layout, 'md_ol_bg', 'Kolor tła')
        self._add_color_row(ol_layout, 'md_ol_marker', 'Kolor numeru')
        self._add_font_row(ol_layout, 'md_ol_font', 'Czcionka')
        self._add_size_row(ol_layout, 'md_ol_size', 'Rozmiar')
        ol_group.setLayout(ol_layout)
        layout.addWidget(ol_group)
        
        # === Linia pozioma ===
        hr_group = QGroupBox("Linia pozioma (---)")
        hr_layout = QFormLayout()
        self._add_color_row(hr_layout, 'md_hr_color', 'Kolor linii')
        
        hr_height_spin = QSpinBox()
        hr_height_spin.setMinimum(1)
        hr_height_spin.setMaximum(50)
        hr_height_spin.setValue(int(self.colors.get('md_hr_height', '2')))
        hr_height_spin.setSuffix(" px")
        self.size_inputs['md_hr_height'] = hr_height_spin
        hr_layout.addRow("Grubość linii:", hr_height_spin)
        
        hr_group.setLayout(hr_layout)
        layout.addWidget(hr_group)
        
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        
        # Przyciski
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Przywróć domyślne")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
    
    def _add_color_row(self, layout, key, label):
        """Dodaje wiersz z przyciskiem koloru"""
        btn = QPushButton()
        btn.setFixedSize(100, 25)
        color = self.colors.get(key, '#ffffff')
        self._update_color_button(btn, color)
        btn.clicked.connect(lambda checked=False, k=key, b=btn: self._choose_color(k, b))
        self.color_buttons[key] = btn
        layout.addRow(f"{label}:", btn)
    
    def _update_color_button(self, btn, color):
        """Aktualizuje wygląd przycisku koloru"""
        if color == 'transparent' or not color:
            btn.setStyleSheet("background-color: white; border: 2px dashed #999;")
            btn.setText("brak")
        else:
            btn.setStyleSheet(f"background-color: {color}; border: 1px solid #999;")
            btn.setText("")
    
    def _add_font_row(self, layout, key, label):
        """Dodaje wiersz z polem czcionki"""
        font_input = QLineEdit()
        font_input.setText(self.colors.get(key, 'inherit'))
        font_input.setPlaceholderText("inherit, Arial, Consolas...")
        self.font_inputs[key] = font_input
        layout.addRow(f"{label}:", font_input)
    
    def _add_size_row(self, layout, key, label):
        """Dodaje wiersz z rozmiarem czcionki"""
        size_spin = QSpinBox()
        size_spin.setMinimum(8)
        size_spin.setMaximum(72)
        try:
            val = int(str(self.colors.get(key, '16')))
        except (ValueError, TypeError):
            val = 16
        size_spin.setValue(val)
        size_spin.setSuffix(" px")
        self.size_inputs[key] = size_spin
        layout.addRow(f"{label}:", size_spin)
    
    def set_font_settings(self, family, size):
        """Ustaw zapisane ustawienia czcionki"""
        self.md_font_family = family
        self.md_font_size = size
        self.font_family_combo.setText(family)
        self.font_size_spin.setValue(size)
        
    def _choose_color(self, key, button):
        current = self.colors.get(key, '#ffffff')
        if current == 'transparent' or not current:
            current = '#ffffff'
        
        # Pytanie czy ustawić transparent
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Wybór koloru")
        msg.setText(f"Co chcesz zrobić z: {key}?")
        btn_color = msg.addButton("Wybierz kolor", QMessageBox.ActionRole)
        btn_transparent = msg.addButton("Ustaw przezroczysty", QMessageBox.ActionRole)
        btn_cancel = msg.addButton("Anuluj", QMessageBox.RejectRole)
        msg.exec()
        
        if msg.clickedButton() == btn_color:
            color = QColorDialog.getColor(QColor(current), self, f"Wybierz kolor")
            if color.isValid():
                self.colors[key] = color.name()
                self._update_color_button(button, color.name())
        elif msg.clickedButton() == btn_transparent:
            self.colors[key] = 'transparent'
            self._update_color_button(button, 'transparent')
            
    def reset_to_defaults(self):
        default_scheme = ColorScheme()
        self.colors = default_scheme.dark.copy() if self.mode == 'dark' else default_scheme.light.copy()
        
        self.md_font_family = "system-ui"
        self.md_font_size = 16
        self.font_family_combo.setText(self.md_font_family)
        self.font_size_spin.setValue(self.md_font_size)
        
        for key, btn in self.color_buttons.items():
            color = self.colors.get(key, '#ffffff')
            self._update_color_button(btn, color)
        
        for key, input_field in self.font_inputs.items():
            val = self.colors.get(key, 'inherit')
            input_field.setText(val if val else 'inherit')
        
        for key, spin in self.size_inputs.items():
            val = self.colors.get(key, '16')
            try:
                spin.setValue(int(val))
            except:
                spin.setValue(16)
        
        # Reset checkboxa podkreślenia
        if hasattr(self, 'link_underline_check'):
            self.link_underline_check.setChecked(self.colors.get('md_link_underline', 'false') == 'true')
        
        # Reset odstępu między liniami
        if hasattr(self, 'line_height_spin'):
            self.line_height_spin.setValue(float(self.colors.get('md_line_height', '1')))
        
        # Reset ustawień cytatu
        if hasattr(self, 'quote_bar_width_spin'):
            self.quote_bar_width_spin.setValue(int(self.colors.get('md_quote_bar_width', '4')))
        if hasattr(self, 'quote_italic_check'):
            self.quote_italic_check.setChecked(self.colors.get('md_quote_italic', 'true') == 'true')
            
    def get_colors(self):
        for key, input_field in self.font_inputs.items():
            self.colors[key] = input_field.text() or 'inherit'
        
        for key, spin in self.size_inputs.items():
            self.colors[key] = str(spin.value())
        
        # Zapisz checkbox podkreślenia
        if hasattr(self, 'link_underline_check'):
            self.colors['md_link_underline'] = 'true' if self.link_underline_check.isChecked() else 'false'
        
        # Zapisz odstęp między liniami
        if hasattr(self, 'line_height_spin'):
            self.colors['md_line_height'] = str(self.line_height_spin.value())
        
        # Zapisz ustawienia cytatu
        if hasattr(self, 'quote_bar_width_spin'):
            self.colors['md_quote_bar_width'] = str(self.quote_bar_width_spin.value())
        
        # Zapisz padding bloku kodu
        if hasattr(self, 'pre_padding_spin'):
            self.colors['md_pre_padding'] = str(self.pre_padding_spin.value())
        if hasattr(self, 'quote_italic_check'):
            self.colors['md_quote_italic'] = 'true' if self.quote_italic_check.isChecked() else 'false'
        
        return self.colors
    
    def get_font_settings(self):
        return {
            'family': self.font_family_combo.text(),
            'size': self.font_size_spin.value()
        }


class ColorCustomizerDialog(QDialog):
    """Dialog do personalizacji kolorów interfejsu"""
    
    def __init__(self, colors, mode, parent=None):
        super().__init__(parent)
        self.colors = colors.copy()
        self.mode = mode
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(f"Personalizuj kolory - Motyw {'ciemny' if self.mode == 'dark' else 'jasny'}")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        app_group = QGroupBox("Kolory interfejsu aplikacji")
        app_layout = QFormLayout()
        
        self.color_buttons = {}
        
        app_colors = [
            ('window', 'Tło okna'),
            ('text', 'Tekst'),
            ('base', 'Tło edytora'),
            ('button', 'Przyciski'),
            ('highlight', 'Podświetlenie')
        ]
        
        for key, label in app_colors:
            btn = self.create_color_button(key)
            self.color_buttons[key] = btn
            app_layout.addRow(label + ':', btn)
            
        app_group.setLayout(app_layout)
        layout.addWidget(app_group)
        
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Przywróć domyślne")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def create_color_button(self, key):
        btn = QPushButton()
        btn.setFixedSize(100, 30)
        color = self.colors[key]
        btn.setStyleSheet(f"background-color: {color}; border: 1px solid #999;")
        btn.clicked.connect(lambda: self.choose_color(key, btn))
        return btn
        
    def choose_color(self, key, button):
        current_color = QColor(self.colors[key])
        color = QColorDialog.getColor(current_color, self, "Wybierz kolor")
        
        if color.isValid():
            self.colors[key] = color.name()
            button.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #999;")
            
    def reset_to_defaults(self):
        default_scheme = ColorScheme()
        default_colors = default_scheme.dark.copy() if self.mode == 'dark' else default_scheme.light.copy()
        
        for key, btn in self.color_buttons.items():
            if key in default_colors:
                self.colors[key] = default_colors[key]
                btn.setStyleSheet(f"background-color: {default_colors[key]}; border: 1px solid #999;")
            
    def get_colors(self):
        return self.colors


class MarkdownConverter:
    """Konwerter Markdown -> HTML z live preview"""
    
    @staticmethod
    def convert_table(rows):
        if not rows:
            return ''
        
        # Najpierw znajdź wiersz separatora i wyciągnij wyrównanie
        alignments = []
        separator_index = -1
        
        for i, row in enumerate(rows):
            row = row.strip()
            if not row.startswith('|') or not row.endswith('|'):
                continue
            
            cells = [c.strip() for c in row[1:-1].split('|')]
            
            # Sprawdź czy to wiersz separatora (zawiera -, opcjonalnie :)
            if all(re.match(r'^:?-+:?$', c.strip()) for c in cells if c.strip()):
                separator_index = i
                for c in cells:
                    c = c.strip()
                    if c.startswith(':') and c.endswith(':'):
                        alignments.append('center')
                    elif c.endswith(':'):
                        alignments.append('right')
                    elif c.startswith(':'):
                        alignments.append('left')
                    else:
                        alignments.append('left')
                break
        
        html = '<table>'
        
        for i, row in enumerate(rows):
            row = row.strip()
            if not row.startswith('|') or not row.endswith('|'):
                continue
                
            cells = [c.strip() for c in row[1:-1].split('|')]
            
            # Pomiń wiersz separatora
            if all(re.match(r'^:?-+:?$', c.strip()) for c in cells if c.strip()):
                continue
            
            # Nagłówek (przed separatorem)
            if separator_index > 0 and i < separator_index:
                html += '<tr>'
                for j, c in enumerate(cells):
                    align = alignments[j] if j < len(alignments) else 'left'
                    html += f'<th style="text-align: {align};">{c}</th>'
                html += '</tr>'
            else:
                # Zwykły wiersz
                html += '<tr>'
                for j, c in enumerate(cells):
                    align = alignments[j] if j < len(alignments) else 'left'
                    html += f'<td style="text-align: {align};">{c}</td>'
                html += '</tr>'
        
        html += '</table>'
        return html
    @staticmethod
    def process_lists(text):
        """Przetwarzanie list z obsługą zagnieżdżeń"""
        lines = text.split('\n')
        result = []
        list_stack = []  # Stack of (list_type, indent_level)
        
        def get_indent(line):
            """Zwraca liczbę spacji na początku linii"""
            return len(line) - len(line.lstrip())
        
        def get_list_style(list_type, level):
            """Zwraca styl listy dla danego poziomu"""
            if list_type == 'ol':
                styles = ['decimal', 'lower-alpha', 'lower-roman']
                return styles[min(level, len(styles) - 1)]
            else:
                styles = ['disc', 'circle', 'square']
                return styles[min(level, len(styles) - 1)]
        
        def close_lists_to_level(target_level):
            """Zamyka listy do określonego poziomu"""
            html = ''
            while list_stack and list_stack[-1][1] >= target_level:
                closed_type, _ = list_stack.pop()
                html += f'</{closed_type}>'
            return html
        
        i = 0
        while i < len(lines):
            line = lines[i]
            original_line = line
            indent = get_indent(line)
            stripped = line.lstrip()
            
            # Sprawdź czy to lista nieuporządkowana
            ul_match = re.match(r'^[\*\-\+]\s+(.+)$', stripped)
            # Sprawdź czy to lista numerowana
            ol_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
            
            if ul_match:
                content = ul_match.group(1)
                level = indent // 2  # Każde 2 spacje = 1 poziom
                
                # Zamknij listy o wyższym poziomie zagnieżdżenia
                result.append(close_lists_to_level(level + 1))
                
                # Sprawdź czy potrzebujemy nowej listy
                if not list_stack or list_stack[-1][1] < level or list_stack[-1][0] != 'ul':
                    # Zamknij poprzednią listę innego typu na tym samym poziomie
                    if list_stack and list_stack[-1][1] == level and list_stack[-1][0] != 'ul':
                        closed_type, _ = list_stack.pop()
                        result.append(f'</{closed_type}>')
                    
                    style = get_list_style('ul', level)
                    result.append(f'<ul style="list-style-type: {style};">')
                    list_stack.append(('ul', level))
                
                result.append(f'<li>{content}</li>')
                
            elif ol_match:
                num = ol_match.group(1)
                content = ol_match.group(2)
                level = indent // 2
                
                # Zamknij listy o wyższym poziomie zagnieżdżenia
                result.append(close_lists_to_level(level + 1))
                
                # Sprawdź czy potrzebujemy nowej listy
                if not list_stack or list_stack[-1][1] < level or list_stack[-1][0] != 'ol':
                    # Zamknij poprzednią listę innego typu na tym samym poziomie
                    if list_stack and list_stack[-1][1] == level and list_stack[-1][0] != 'ol':
                        closed_type, _ = list_stack.pop()
                        result.append(f'</{closed_type}>')
                    
                    style = get_list_style('ol', level)
                    result.append(f'<ol style="list-style-type: {style};">')
                    list_stack.append(('ol', level))
                
                result.append(f'<li>{content}</li>')
                
            else:
                # Nie jest to element listy - zamknij wszystkie otwarte listy
                if stripped:  # Tylko jeśli linia nie jest pusta
                    result.append(close_lists_to_level(0))
                result.append(original_line)
            
            i += 1
        
        # Zamknij wszystkie pozostałe listy
        result.append(close_lists_to_level(0))
        
        return '\n'.join(result)
    
    @staticmethod
    def to_html(markdown, colors, font_family="system-ui", font_size=16):
        def get(key, default=''):
            val = colors.get(key, default)
            return val if val else default
        
        def bg_style(key):
            val = get(key, 'transparent')
            if val == 'transparent' or not val:
                return 'transparent'
            return val
        
        def font_family_style(key, default='inherit'):
            val = get(key, default)
            if not val or val == 'inherit':
                return 'inherit'
            return val
        
        # Pobierz ustawienia
        link_underline = get('md_link_underline', 'false') == 'true'
        link_decoration = 'underline' if link_underline else 'none'
        line_height = get('md_line_height', '1')
        
        html_head = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        font-family: {font_family};
        font-size: {font_size}px;
        line-height: {line_height};
        padding: 20px;
        max-width: 800px;
        background-color: {get('md_bg', '#ffffff')};
        color: {get('md_text', '#2c3e50')};
    }}
    
    /* === NAGŁÓWKI === */
    h1 {{ 
        color: {get('md_h1_color', '#1a5276')}; 
        background-color: {bg_style('md_h1_bg')};
        font-family: {font_family_style('md_h1_font')};
        font-size: {get('md_h1_size', '40')}px;
        border-bottom: 3px solid {get('md_border', '#3498db')}; 
        padding: 8px 4px 10px 4px;
        margin-top: 24px;
        margin-bottom: 12px;
        line-height: 1.3;
    }}
    h2 {{ 
        color: {get('md_h2_color', '#1e8449')}; 
        background-color: {bg_style('md_h2_bg')};
        font-family: {font_family_style('md_h2_font')};
        font-size: {get('md_h2_size', '24')}px;
        border-bottom: 2px solid {get('md_border', '#3498db')}; 
        padding: 6px 4px 8px 4px;
        margin-top: 20px;
        margin-bottom: 10px;
        line-height: 1.3;
    }}
    h3 {{ 
        color: {get('md_h3_color', '#7d3c98')}; 
        background-color: {bg_style('md_h3_bg')};
        font-family: {font_family_style('md_h3_font')};
        font-size: {get('md_h3_size', '20')}px;
        margin-top: 18px;
        margin-bottom: 8px;
        padding: 4px;
        line-height: 1.3;
    }}
    h4 {{ 
        color: {get('md_h4_color', '#b8860b')}; 
        background-color: {bg_style('md_h4_bg')};
        font-family: {font_family_style('md_h4_font')};
        font-size: {get('md_h4_size', '18')}px;
        margin-top: 16px;
        margin-bottom: 6px;
        padding: 4px;
        line-height: 1.3;
    }}
    h5 {{ 
        color: {get('md_h5_color', '#2e8b57')}; 
        background-color: {bg_style('md_h5_bg')};
        font-family: {font_family_style('md_h5_font')};
        font-size: {get('md_h5_size', '16')}px;
        margin-top: 12px;
        margin-bottom: 6px;
        padding: 4px;
        line-height: 1.3;
    }}
    h6 {{ 
        color: {get('md_h6_color', '#4682b4')}; 
        background-color: {bg_style('md_h6_bg')};
        font-family: {font_family_style('md_h6_font')};
        font-size: {get('md_h6_size', '14')}px;
        margin-top: 12px;
        margin-bottom: 6px;
        padding: 4px;
        line-height: 1.3;
    }}
    
    /* === BLOK KODU (pre) === */
    .code-container {{
        position: relative;
        margin: 16px 0;
    }}
    .copy-btn {{
        position: absolute;
        bottom: 8px;
        right: 8px;
        background: rgba(255,255,255,0.15);
        border: 1px solid rgba(255,255,255,0.3);
        border-radius: 4px;
        padding: 4px 8px;
        color: #888;
        font-size: 14px;
        text-decoration: none;
        cursor: pointer;
    }}
    .copy-btn:hover {{
        background: rgba(255,255,255,0.25);
        color: #fff;
    }}
    pre {{
        display: block;
        background-color: {get('md_pre_bg', '#2d2d2d')};
        color: {get('md_pre_text', '#f0f0f0')};
        font-family: {font_family_style('md_pre_font', 'Consolas, monospace')};
        font-size: {get('md_pre_size', '14')}px;
        border-radius: 8px;
        padding: {get('md_pre_padding', '16')}px {get('md_pre_padding', '16')}px calc({get('md_pre_padding', '16')}px + 20px) {get('md_pre_padding', '16')}px;
        margin: 0;
        overflow-x: auto;
        border: 1px solid {get('md_table_border', '#404040')};
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        line-height: 1;
        white-space: pre;
        word-wrap: normal;
    }}
    
    /* === KOD INLINE === */
    code.inline {{
        background-color: {get('md_code_bg', '#f4f4f4')};
        color: {get('md_code_text', '#c0392b')};
        font-family: {font_family_style('md_code_font', 'Consolas, monospace')};
        font-size: {get('md_code_size', '14')}px;
        padding: 2px 6px;
        border-radius: 4px;
        white-space: nowrap;
    }}
    
    /* === CYTAT (styl Discord) === */
    blockquote {{
        border-left-width: {get('md_quote_bar_width', '4')}px;
        border-left-style: solid;
        border-left-color: {get('md_quote_border', get('md_border', '#3498db'))};
        margin-top: 8px;
        margin-bottom: 8px;
        margin-left: 0;
        padding-top: 4px;
        padding-right: 0;
        padding-bottom: 4px;
        padding-left: 12px;
        color: {get('md_quote_text', '#555555')};
        background-color: {bg_style('md_quote_bg')};
        font-family: {font_family_style('md_quote_font', 'inherit')};
        font-size: {get('md_quote_size', '16')}px;
        font-style: {'italic' if get('md_quote_italic', 'true') == 'true' else 'normal'};
        border-radius: 0 4px 4px 0;
        display: block;
        line-height: 1.4;
    }}
    blockquote p {{
        margin: 0;
        padding: 0;
        display: inline;
    }}
    
    /* === LISTY === */
    ul {{ 
        padding-left: 30px;
        margin: 12px 0;
        color: {get('md_ul_color', '#2c3e50')};
        background-color: {bg_style('md_ul_bg')};
        font-family: {font_family_style('md_ul_font')};
        font-size: {get('md_ul_size', '16')}px;
        list-style-type: disc;
    }}
    ul li::marker {{
        color: {get('md_ul_marker', '#3498db')};
    }}
    ol {{ 
        padding-left: 30px;
        margin: 12px 0;
        color: {get('md_ol_color', '#2c3e50')};
        background-color: {bg_style('md_ol_bg')};
        font-family: {font_family_style('md_ol_font')};
        font-size: {get('md_ol_size', '16')}px;
    }}
    ol li::marker {{
        color: {get('md_ol_marker', '#e74c3c')};
        font-weight: bold;
    }}
    li {{ 
        margin: 8px 0; 
    }}
    
    /* === LINKI === */
    a {{ 
        color: {get('md_link', '#3498db')}; 
        background-color: {bg_style('md_link_bg')};
        font-family: {font_family_style('md_link_font')};
        font-size: {get('md_link_size', '16')}px;
        text-decoration: {link_decoration};
        cursor: pointer;
    }}
    a:hover {{ 
        color: {get('md_link_hover', '#2980b9')};
        text-decoration: underline; 
    }}
    
    /* === LINIA POZIOMA === */
    hr {{ 
        border: none; 
        height: {get('md_hr_height', '2')}px;
        background-color: {get('md_hr_color', '#cccccc')}; 
        margin: 30px 0; 
    }}
    
    /* === TABELA === */
    table {{ 
        border-collapse: collapse; 
        width: 100%; 
        margin: 20px 0;
        border: 2px solid {get('md_table_border', '#dddddd')};
        font-family: {font_family_style('md_table_font')};
        font-size: {get('md_table_size', '14')}px;
        color: {get('md_table_text', '#2c3e50')};
    }}
    th, td {{ 
        border: 1px solid {get('md_table_border', '#dddddd')}; 
        padding: 12px; 
        text-align: left; 
    }}
    td {{
        background-color: {bg_style('md_table_bg')};
    }}
    th {{ 
        background-color: {get('md_table_header_bg', '#3498db')}; 
        color: {get('md_table_header_text', '#ffffff')};
        font-weight: bold; 
    }}
    
    /* === POZOSTAŁE === */
    img {{ 
        max-width: 100%; 
        height: auto; 
        border-radius: 8px;
        margin: 15px 0;
        display: block;
    }}
    p {{
        margin: 12px 0;
    }}
    del {{
        text-decoration: line-through;
        color: #888888;
    }}
    u {{
        text-decoration: underline;
    }}
</style>
</head>
<body>
"""
        
        text = markdown
        
        # Najpierw wyciągnij bloki kodu i zastąp placeholderami
        code_blocks = []
        
        def save_code_block(match):
            lang = match.group(1) or ''
            code = match.group(2)
            original_code = code  # Zachowaj oryginalny kod przed escape
            # Escape HTML wewnątrz bloku kodu
            code = code.replace('&', '&amp;')
            code = code.replace('<', '&lt;')
            code = code.replace('>', '&gt;')
            # Zachowaj blok kodu z przyciskiem kopiowania
            index = len(code_blocks)
            code_b64 = base64.urlsafe_b64encode(original_code.encode('utf-8')).decode('ascii')
            code_blocks.append(f'<div class="code-container"><pre>{code}</pre><a href="copy:{code_b64}" class="copy-btn">📋</a></div>')
            return f'%%CODEBLOCK_{index}%%'
        
        text = re.sub(r'```(\w*)\n(.*?)```', save_code_block, text, flags=re.DOTALL)
        
        # Obsługa podwójnej spacji jako nowej linii (przed escape)
        text = re.sub(r'  \n', '<br>\n', text)
        text = re.sub(r'  $', '<br>', text, flags=re.MULTILINE)
        
        text = text.replace('<u>', '%%UNDERLINE_START%%')
        text = text.replace('</u>', '%%UNDERLINE_END%%')
        text = text.replace('<br>', '%%BR%%')
        
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        
        text = text.replace('%%UNDERLINE_START%%', '<u>')
        text = text.replace('%%UNDERLINE_END%%', '</u>')
        text = text.replace('%%BR%%', '<br>')
        
        lines = text.split('\n')
        new_lines = []
        table_rows = []
        in_table = False
        
        for line in lines:
            stripped = line.strip()
            if re.match(r'^\|.*\|$', stripped):
                in_table = True
                table_rows.append(line)
            else:
                if in_table and table_rows:
                    new_lines.append(MarkdownConverter.convert_table(table_rows))
                    table_rows = []
                    in_table = False
                new_lines.append(line)
        
        if table_rows:
            new_lines.append(MarkdownConverter.convert_table(table_rows))
        
        text = '\n'.join(new_lines)
        
        # Nagłówki - wymuszamy inline style aby nadpisać CSS
        text = re.sub(
            r'^###### (.+)$',
            lambda m: f'<h6 style="font-size: {get("md_h6_size", "14")}px;">{m.group(1)}</h6>',
            text, flags=re.MULTILINE
        )
        text = re.sub(
            r'^##### (.+)$',
            lambda m: f'<h5 style="font-size: {get("md_h5_size", "16")}px;">{m.group(1)}</h5>',
            text, flags=re.MULTILINE
        )
        text = re.sub(
            r'^#### (.+)$',
            lambda m: f'<h4 style="font-size: {get("md_h4_size", "18")}px;">{m.group(1)}</h4>',
            text, flags=re.MULTILINE
        )
        text = re.sub(
            r'^### (.+)$',
            lambda m: f'<h3 style="font-size: {get("md_h3_size", "20")}px;">{m.group(1)}</h3>',
            text, flags=re.MULTILINE
        )
        text = re.sub(
            r'^## (.+)$',
            lambda m: f'<h2 style="font-size: {get("md_h2_size", "24")}px;">{m.group(1)}</h2>',
            text, flags=re.MULTILINE
        )
        text = re.sub(
            r'^# (.+)$',
            lambda m: f'<h1 style="font-size: {get("md_h1_size", "40")}px;">{m.group(1)}</h1>',
            text, flags=re.MULTILINE
        )
        
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
        
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)
        
        # Kod inline - użyj klasy "inline" aby odróżnić od bloku
        text = re.sub(r'`([^`]+)`', r'<code class="inline">\1</code>', text)
        
        text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)
        #text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)
        
        # Obrazki - obsługa lokalnych plików i URL
        def convert_image(match):
            alt = match.group(1)
            src = match.group(2)
            
            # Dla URL-i zewnętrznych - użyj bezpośrednio
            if src.startswith(('http://', 'https://', 'data:')):
                return f'<img src="{src}" alt="{alt}">'
            
            # Dla lokalnych plików - konwertuj do base64
            try:
                # Obsłuż różne formaty ścieżek
                src_clean = src.replace('\\', '/')
                if src_clean.startswith('file:///'):
                    src_clean = src_clean[8:]
                
                src_path = Path(src_clean)
                
                if src_path.exists() and src_path.is_file():
                    # Określ typ MIME
                    suffix = src_path.suffix.lower()
                    mime_types = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.bmp': 'image/bmp',
                        '.webp': 'image/webp',
                        '.svg': 'image/svg+xml'
                    }
                    mime_type = mime_types.get(suffix, 'image/png')
                    
                    # Wczytaj i zakoduj w base64
                    with open(src_path, 'rb') as f:
                        img_data = f.read()
                    img_base64 = base64.b64encode(img_data).decode('ascii')
                    
                    return f'<img src="data:{mime_type};base64,{img_base64}" alt="{alt}">'
                else:
                    # Plik nie istnieje - pokaż placeholder
                    return f'<span style="color: red; border: 1px dashed red; padding: 4px;">[Obrazek nie znaleziony: {alt}]</span>'
            except Exception as e:
                return f'<span style="color: red;">[Błąd ładowania obrazka: {alt}]</span>'
        
        text = re.sub(r'!\[([^\]]+)\]\(([^\)]+)\)', convert_image, text)
        
        text = re.sub(r'^---$', r'<hr>', text, flags=re.MULTILINE)
        text = re.sub(r'^\*\*\*$', r'<hr>', text, flags=re.MULTILINE)
        
        # Przetwarzanie list (z obsługą zagnieżdżeń)
        text = MarkdownConverter.process_lists(text)
        
        def process_quotes(text):
            """Przetwarzanie cytatów z obsługą zagnieżdżeń"""
            lines = text.split('\n')
            result = []
            
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Zlicz poziom cytatu (ile razy &gt; na początku)
                def get_quote_level(ln):
                    level = 0
                    temp = ln
                    while temp.startswith('&gt;'):
                        level += 1
                        temp = temp[4:]
                        if temp.startswith(' '):
                            temp = temp[1:]
                    return level, temp
                
                level, content = get_quote_level(line)
                
                if level > 0:
                    # Zbierz wszystkie kolejne linie cytatu
                    quote_lines = [(level, content)]
                    i += 1
                    
                    while i < len(lines):
                        next_line = lines[i]
                        next_level, next_content = get_quote_level(next_line)
                        
                        if next_level > 0:
                            quote_lines.append((next_level, next_content))
                            i += 1
                        elif not next_line.strip():
                            # Pusta linia - sprawdź czy następna też jest cytatem
                            if i + 1 < len(lines):
                                peek_level, _ = get_quote_level(lines[i + 1])
                                if peek_level > 0:
                                    # Pusta linia między cytatami - kontynuuj
                                    i += 1
                                    continue
                            break
                        else:
                            break
                    
                    # Buduj zagnieżdżone blockquote
                    def build_quote(items, start_idx, min_level):
                        if start_idx >= len(items):
                            return '', start_idx
                        
                        html_parts = []
                        idx = start_idx
                        
                        while idx < len(items):
                            item_level, item_content = items[idx]
                            
                            if item_level < min_level:
                                break
                            elif item_level == min_level:
                                html_parts.append(item_content)
                                idx += 1
                            else:
                                # Zagnieżdżony cytat
                                nested_html, idx = build_quote(items, idx, item_level)
                                html_parts.append(f'<blockquote>{nested_html}</blockquote>')
                        
                        return '<br>'.join(html_parts), idx
                    
                    # Znajdź minimalny poziom
                    min_level = min(lvl for lvl, _ in quote_lines)
                    quote_html, _ = build_quote(quote_lines, 0, min_level)
                    result.append(f'<blockquote>{quote_html}</blockquote>')
                else:
                    result.append(line)
                    i += 1
            
            return '\n'.join(result)
        
        text = process_quotes(text)
        
        # Przetwarzanie akapitów - podwójny Enter = nowy akapit, pojedynczy = spacja
        lines = text.split('\n')
        result = []
        in_pre = False
        paragraph_lines = []
        
        def flush_paragraph():
            if paragraph_lines:
                # Połącz linie spacjami (pojedynczy Enter = spacja)
                content = ' '.join(paragraph_lines)
                result.append(f'<p>{content}</p>')
                paragraph_lines.clear()
        
        for line in lines:
            stripped = line.strip()
            
            if '<pre>' in line:
                in_pre = True
                flush_paragraph()
                result.append(line)
                continue
            if '</pre>' in line:
                in_pre = False
                result.append(line)
                continue
            
            if in_pre:
                result.append(line)
            elif stripped:
                # Sprawdź czy to placeholder bloku kodu
                if stripped.startswith('%%CODEBLOCK_'):
                    flush_paragraph()
                    result.append(line)
                elif stripped.startswith('<'):
                    flush_paragraph()
                    result.append(line)
                else:
                    # Zbieraj linie do akapitu
                    paragraph_lines.append(stripped)
            else:
                # Pusta linia = koniec akapitu (podwójny Enter)
                flush_paragraph()
                result.append('')
        
        # Opróżnij pozostałe linie
        flush_paragraph()
        
        text = '\n'.join(result)
        
        # Przywróć bloki kodu
        for i, code_block in enumerate(code_blocks):
            text = text.replace(f'%%CODEBLOCK_{i}%%', code_block)
        
        html = html_head + text + "</body></html>"
        return html

class TextEditor(QMainWindow):
    """Główne okno edytora tekstowego"""
    
    def __init__(self):
        super().__init__()
        self.is_dark_mode = False
        self.scroll_lines = 1
        self.view_mode = 1
        
        # Ustawienia czcionki Markdown
        self.md_font_family = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
        self.md_font_size = 16
        
        self.shortcuts = {
            'move_up': 'Alt+Up',
            'move_down': 'Alt+Down',
            'duplicate': 'Ctrl+D'
        }
        
        self.default_view_mode = 1  # Domyślny tryb widoku dla nowych dokumentów
        self.md_default_view_mode = 1  # Domyślny tryb widoku dla plików .md (0, 1, 2)
        self.duplicate_with_newline = True  # Czy duplikowanie zaznaczenia dodaje nową linię
        
        self.settings = QSettings('TextEditor', 'UniPadPlusPlus')
        self.color_scheme = ColorScheme()
        
        self.find_dialog = None
        
        self.load_settings()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("UniPad++")
        self.setGeometry(100, 100, 1200, 800)
        
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Pasek kart z własnym TabBar
        self.tab_widget = QTabWidget()
        self.custom_tab_bar = CloseableTabBar()
        self.tab_widget.setTabBar(self.custom_tab_bar)
        self.tab_widget.setTabsClosable(False)  # Wyłączamy domyślny przycisk zamknięcia
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        
        # Podłączamy własny sygnał zamknięcia
        self.custom_tab_bar.close_tab_requested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        self.create_markdown_toolbar()
        main_layout.addWidget(self.markdown_toolbar)
        main_layout.addWidget(self.tab_widget)
        
        self.setCentralWidget(central_widget)
        
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(300)
        self.update_timer.timeout.connect(self.update_preview)
        
        self.create_menus()
        self.setup_shortcuts()
        
        self.new_file()
        
        self.statusBar().showMessage("Gotowy")
        self.apply_theme()
        
        # Początkowa aktualizacja paska narzędzi (po pokazaniu okna)
        QTimer.singleShot(200, self.update_toolbar_overflow)
        
    def setup_shortcuts(self):
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self.open_find_dialog)
    
    def get_current_tab(self):
        return self.tab_widget.currentWidget()
    
    def get_current_editor(self):
        tab = self.get_current_tab()
        if tab:
            return tab.text_edit
        return None
    
    def new_file(self):
        tab = EditorTab()
        tab.text_edit.set_scroll_lines(self.scroll_lines)
        tab.text_edit.duplicate_with_newline = self.duplicate_with_newline
        tab.text_edit.set_shortcuts(
            self.shortcuts.get('move_up', 'Alt+Up'),
            self.shortcuts.get('move_down', 'Alt+Down'),
            self.shortcuts.get('duplicate', 'Ctrl+D')
        )
        tab.content_changed.connect(lambda: self.on_content_changed(tab))
        tab.preview.anchorClicked.connect(self.open_link)
        
        saved_font = QFont(
            self.settings.value('font_family', 'Consolas', type=str),
            self.settings.value('font_size', 11, type=int)
        )
        tab.text_edit.setFont(saved_font)
        tab.text_edit.set_dark_mode(self.is_dark_mode)
        tab.set_view_mode(self.default_view_mode)
        
        index = self.tab_widget.addTab(tab, "Nowy plik")
        self.tab_widget.setCurrentIndex(index)
        
        return tab
    
    def close_tab(self, index):
        tab = self.tab_widget.widget(index)
        
        if tab.is_modified():
            reply = QMessageBox.question(
                self, "Potwierdź",
                "Dokument został zmodyfikowany.\nCzy chcesz zapisać zmiany?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                self.tab_widget.setCurrentIndex(index)
                self.save_file()
            elif reply == QMessageBox.Cancel:
                return
        
        self.tab_widget.removeTab(index)
        
        if self.tab_widget.count() == 0:
            self.new_file()
    
    def on_tab_changed(self, index):
        tab = self.tab_widget.widget(index)
        if tab:
            self.update_window_title()
            self.update_preview()
    
    def on_content_changed(self, tab):
        index = self.tab_widget.indexOf(tab)
        if index >= 0:
            title = self.tab_widget.tabText(index)
            if not title.endswith('*'):
                self.tab_widget.setTabText(index, title + '*')
        
        self.update_timer.start()
    
    def update_window_title(self):
        tab = self.get_current_tab()
        if tab and tab.file_path:
            self.setWindowTitle(f"UniPad++ - {tab.file_path}")
        else:
            self.setWindowTitle("UniPad++ - Nowy plik")
    
    def open_link(self, url):
        url_str = url.toString()
        if url_str.startswith('copy:'):
            # Zachowaj pozycję scrolla
            tab = self.get_current_tab()
            if tab:
                scroll_pos = tab.preview.verticalScrollBar().value()
            
            code_b64 = url_str.replace('copy:', '')
            try:
                code = base64.urlsafe_b64decode(code_b64).decode('utf-8')
                QApplication.clipboard().setText(code)
                self.statusBar().showMessage("Skopiowano kod do schowka", 2000)
            except Exception as e:
                self.statusBar().showMessage(f"Błąd kopiowania: {e}", 2000)
            
            # Przywróć pozycję scrolla
            if tab:
                QTimer.singleShot(10, lambda: tab.preview.verticalScrollBar().setValue(scroll_pos))
        else:
            QDesktopServices.openUrl(url)
        
    def create_menus(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("&Plik")
        
        new_action = QAction("&Nowy", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Otwórz...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        
        save_action = QAction("&Zapisz", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Zapisz &jako...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_file_as)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        close_tab_action = QAction("Zamknij &kartę", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(lambda: self.close_tab(self.tab_widget.currentIndex()))
        file_menu.addAction(close_tab_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("&Wyjście", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        edit_menu = menubar.addMenu("&Edycja")
        
        find_action = QAction("&Znajdź i zamień...", self)
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(self.open_find_dialog)
        edit_menu.addAction(find_action)
        
        edit_menu.addSeparator()
        
        dup_line_action = QAction("&Duplikuj linię/zaznaczenie", self)
        dup_line_action.setShortcut(self.shortcuts.get('duplicate', 'Ctrl+D'))
        dup_line_action.triggered.connect(self.duplicate_current_line)
        edit_menu.addAction(dup_line_action)
        
        move_up_action = QAction("Przesuń linie w &górę", self)
        move_up_action.setShortcut(self.shortcuts.get('move_up', 'Alt+Up'))
        move_up_action.triggered.connect(self.move_line_up)
        edit_menu.addAction(move_up_action)
        
        move_down_action = QAction("Przesuń linie w &dół", self)
        move_down_action.setShortcut(self.shortcuts.get('move_down', 'Alt+Down'))
        move_down_action.triggered.connect(self.move_line_down)
        edit_menu.addAction(move_down_action)
        
        edit_menu.addSeparator()
        
        duplicate_newline_action = QAction("Duplikuj zaznaczenie w &nowej linii", self)
        duplicate_newline_action.setCheckable(True)
        duplicate_newline_action.setChecked(self.duplicate_with_newline)
        duplicate_newline_action.triggered.connect(self.toggle_duplicate_newline)
        edit_menu.addAction(duplicate_newline_action)
        
        edit_menu.addSeparator()
        
        shortcut_settings_action = QAction("Ustawienia &skrótów klawiszowych...", self)
        shortcut_settings_action.triggered.connect(self.open_shortcut_settings)
        edit_menu.addAction(shortcut_settings_action)
        
        view_menu = menubar.addMenu("&Widok")
        
        dark_mode_action = QAction("Ciemny &motyw", self)
        dark_mode_action.setCheckable(True)
        dark_mode_action.setChecked(self.is_dark_mode)
        dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(dark_mode_action)
        
        view_menu.addSeparator()
        
        scroll_settings_action = QAction("Ustawienia &przewijania...", self)
        scroll_settings_action.triggered.connect(self.open_scroll_settings)
        view_menu.addAction(scroll_settings_action)
        
        customize_action = QAction("Personalizuj kolory &interfejsu...", self)
        customize_action.triggered.connect(self.customize_colors)
        view_menu.addAction(customize_action)
        
        markdown_style_action = QAction("Style podglądu &Markdown...", self)
        markdown_style_action.setShortcut("Ctrl+K")
        markdown_style_action.triggered.connect(self.customize_markdown_styles)
        view_menu.addAction(markdown_style_action)
        
        view_menu.addSeparator()
        
        default_view_menu = view_menu.addMenu("Domyślny widok nowych dokumentów")
        
        self.default_view_actions = []
        view_options = [
            (0, "Tylko kod"),
            (1, "Kod + Podgląd"),
            (2, "Tylko podgląd")
        ]
        
        for mode, label in view_options:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.default_view_mode)
            action.triggered.connect(lambda checked, m=mode: self.set_default_view_mode(m))
            default_view_menu.addAction(action)
            self.default_view_actions.append(action)
        
        # Menu dla plików Markdown
        md_view_menu = view_menu.addMenu("Domyślny widok dla plików .md")
        
        self.md_view_actions = []
        
        for mode, label in view_options:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.md_default_view_mode)
            action.triggered.connect(lambda checked, m=mode: self.set_md_default_view(m))
            md_view_menu.addAction(action)
            self.md_view_actions.append(action)
        
        format_menu = menubar.addMenu("F&ormat")
        
        font_action = QAction("Wybierz &czcionkę...", self)
        font_action.setShortcut("Ctrl+T")
        font_action.triggered.connect(self.choose_font)
        format_menu.addAction(font_action)
        
        font_size_menu = format_menu.addMenu("Rozmiar czcionki")
        for size in [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24]:
            size_action = QAction(f"{size} pt", self)
            size_action.triggered.connect(lambda checked, s=size: self.set_font_size(s))
            font_size_menu.addAction(size_action)
        
        # Menu Informacje
        info_menu = menubar.addMenu("&Informacje")
        
        about_action = QAction("&O Programie", self)
        about_action.triggered.connect(self.show_about_dialog)
        info_menu.addAction(about_action)
    
        

    def toggle_duplicate_newline(self):
        """Przełącz tryb duplikowania zaznaczenia"""
        self.duplicate_with_newline = not self.duplicate_with_newline
        
        # Aktualizuj wszystkie edytory
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            tab.text_edit.duplicate_with_newline = self.duplicate_with_newline
        
        self.save_settings()
        
        mode_text = "w nowej linii" if self.duplicate_with_newline else "bez nowej linii"
        self.statusBar().showMessage(f"Duplikowanie zaznaczenia: {mode_text}", 2000)
    
    def set_default_view_mode(self, mode):
        self.default_view_mode = mode
        
        # Aktualizuj zaznaczenie w menu
        for i, action in enumerate(self.default_view_actions):
            action.setChecked(i == mode)
        
        self.save_settings()
        mode_names = ["Tylko kod", "Kod + Podgląd", "Tylko podgląd"]
        self.statusBar().showMessage(f"Domyślny widok nowych dokumentów: {mode_names[mode]}", 2000)
    
    def set_md_default_view(self, mode):
        self.md_default_view_mode = mode
        
        # Aktualizuj zaznaczenie w menu
        for i, action in enumerate(self.md_view_actions):
            action.setChecked(i == mode)
        
        self.save_settings()
        mode_names = ["Tylko kod", "Kod + Podgląd", "Tylko podgląd"]
        self.statusBar().showMessage(f"Domyślny widok dla plików .md: {mode_names[mode]}", 2000)
    
    def show_about_dialog(self):
        """Wyświetla okienko O Programie"""
        QMessageBox.information(self, "O Programie", "UniPad++\nWersja 1.2")
    
    def open_find_dialog(self):
        if not self.find_dialog:
            self.find_dialog = FindReplaceDialog(self)
        
        editor = self.get_current_editor()
        if editor:
            self.find_dialog.set_editor(editor)
            
            cursor = editor.textCursor()
            if cursor.hasSelection():
                self.find_dialog.find_input.setText(cursor.selectedText())
        
        self.find_dialog.show()
        self.find_dialog.find_input.setFocus()
        self.find_dialog.find_input.selectAll()
    
    def duplicate_current_line(self):
        editor = self.get_current_editor()
        if editor:
            editor.duplicate_line_or_selection()
    
    def move_line_up(self):
        editor = self.get_current_editor()
        if editor:
            editor.move_lines_up()
    
    def move_line_down(self):
        editor = self.get_current_editor()
        if editor:
            editor.move_lines_down()
    
    def open_scroll_settings(self):
        dialog = ScrollSettingsDialog(self.scroll_lines, self)
        if dialog.exec() == QDialog.Accepted:
            self.scroll_lines = dialog.get_scroll_lines()
            
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                tab.text_edit.set_scroll_lines(self.scroll_lines)
            
            self.save_settings()
            self.statusBar().showMessage(f"Przewijanie: {self.scroll_lines} linia/e na scroll", 2000)
    
    def open_shortcut_settings(self):
        """Otwórz dialog ustawień skrótów klawiszowych"""
        dialog = ShortcutSettingsDialog(self.shortcuts, self)
        if dialog.exec() == QDialog.Accepted:
            self.shortcuts = dialog.get_shortcuts()
            
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                tab.text_edit.set_shortcuts(
                    self.shortcuts.get('move_up', 'Alt+Up'),
                    self.shortcuts.get('move_down', 'Alt+Down'),
                    self.shortcuts.get('duplicate', 'Ctrl+D')
                )
            
            self.save_settings()
            self.statusBar().showMessage("Skróty klawiszowe zaktualizowane", 2000)
    
    def toggle_duplicate_newline(self):
        """Przełącz tryb duplikowania zaznaczenia"""
        self.duplicate_with_newline = not self.duplicate_with_newline
        
        # Aktualizuj wszystkie edytory
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            tab.text_edit.duplicate_with_newline = self.duplicate_with_newline
        
        self.save_settings()
        
        mode_text = "w nowej linii" if self.duplicate_with_newline else "bez nowej linii"
        self.statusBar().showMessage(f"Duplikowanie zaznaczenia: {mode_text}", 2000)
    
    def create_markdown_toolbar(self):
        self.markdown_toolbar = QToolBar("Markdown")
        self.markdown_toolbar.setMovable(False)
        
        # Lista wszystkich akcji do zarządzania overflow
        self.toolbar_actions = []
        
        # Przycisk nowej karty
        new_tab_action = QAction("+", self)
        new_tab_action.setToolTip("Nowa karta (Ctrl+N)")
        new_tab_action.triggered.connect(self.new_file)
        self.markdown_toolbar.addAction(new_tab_action)
        
        self.markdown_toolbar.addSeparator()
        
        # === TRYBY WIDOKU ===
        code_only_action = QAction("📝", self)
        code_only_action.setToolTip("Tylko kod")
        code_only_action.triggered.connect(lambda: self.set_view_mode(0))
        self.markdown_toolbar.addAction(code_only_action)
        
        split_view_action = QAction("📝|👁", self)
        split_view_action.setToolTip("Kod + Podgląd")
        split_view_action.triggered.connect(lambda: self.set_view_mode(1))
        self.markdown_toolbar.addAction(split_view_action)
        
        preview_only_action = QAction("👁", self)
        preview_only_action.setToolTip("Tylko podgląd")
        preview_only_action.triggered.connect(lambda: self.set_view_mode(2))
        self.markdown_toolbar.addAction(preview_only_action)
        
        self.markdown_toolbar.addSeparator()
        
        find_action = QAction("🔍", self)
        find_action.setToolTip("Znajdź i zamień (Ctrl+F)")
        find_action.triggered.connect(self.open_find_dialog)
        self.markdown_toolbar.addAction(find_action)
        
        self.markdown_toolbar.addSeparator()
        
        bold_action = QAction("B", self)
        bold_action.setToolTip("Pogrubienie (Ctrl+B)")
        bold_action.setShortcut("Ctrl+B")
        bold_action.triggered.connect(lambda: self.insert_markdown('**', '**'))
        bold_action.setFont(QFont("Arial", 10, QFont.Bold))
        self.markdown_toolbar.addAction(bold_action)
        
        italic_action = QAction("I", self)
        italic_action.setToolTip("Kursywa (Ctrl+I)")
        italic_action.setShortcut("Ctrl+I")
        italic_action.triggered.connect(lambda: self.insert_markdown('*', '*'))
        italic_font = QFont("Arial", 10)
        italic_font.setItalic(True)
        italic_action.setFont(italic_font)
        self.markdown_toolbar.addAction(italic_action)
        
        strike_action = QAction("S̶", self)
        strike_action.setToolTip("Przekreślenie")
        strike_action.triggered.connect(lambda: self.insert_markdown('~~', '~~'))
        self.markdown_toolbar.addAction(strike_action)
        
        underline_action = QAction("U", self)
        underline_action.setToolTip("Podkreślenie")
        underline_action.triggered.connect(lambda: self.insert_markdown('<u>', '</u>'))
        underline_font = QFont("Arial", 10)
        underline_font.setUnderline(True)
        underline_action.setFont(underline_font)
        self.markdown_toolbar.addAction(underline_action)
        
        self.markdown_toolbar.addSeparator()
        
        h1_action = QAction("H1", self)
        h1_action.setToolTip("Nagłówek 1")
        h1_action.triggered.connect(lambda: self.insert_heading(1))
        self.markdown_toolbar.addAction(h1_action)
        
        h2_action = QAction("H2", self)
        h2_action.setToolTip("Nagłówek 2")
        h2_action.triggered.connect(lambda: self.insert_heading(2))
        self.markdown_toolbar.addAction(h2_action)
        
        h3_action = QAction("H3", self)
        h3_action.setToolTip("Nagłówek 3")
        h3_action.triggered.connect(lambda: self.insert_heading(3))
        self.markdown_toolbar.addAction(h3_action)
        
        h4_action = QAction("H4", self)
        h4_action.setToolTip("Nagłówek 4")
        h4_action.triggered.connect(lambda: self.insert_heading(4))
        self.markdown_toolbar.addAction(h4_action)
        
        h5_action = QAction("H5", self)
        h5_action.setToolTip("Nagłówek 5")
        h5_action.triggered.connect(lambda: self.insert_heading(5))
        self.markdown_toolbar.addAction(h5_action)
        
        h6_action = QAction("H6", self)
        h6_action.setToolTip("Nagłówek 6")
        h6_action.triggered.connect(lambda: self.insert_heading(6))
        self.markdown_toolbar.addAction(h6_action)
        
        self.markdown_toolbar.addSeparator()
        
        link_action = QAction("🔗", self)
        link_action.setToolTip("Wstaw link")
        link_action.triggered.connect(self.insert_link)
        self.markdown_toolbar.addAction(link_action)
        
        image_action = QAction("🖼", self)
        image_action.setToolTip("Wstaw obrazek")
        image_action.triggered.connect(self.insert_image)
        self.markdown_toolbar.addAction(image_action)
        
        code_action = QAction("< >", self)
        code_action.setToolTip("Kod inline")
        code_action.triggered.connect(lambda: self.insert_markdown('`', '`'))
        self.markdown_toolbar.addAction(code_action)
        
        code_block_action = QAction("{ }", self)
        code_block_action.setToolTip("Blok kodu")
        code_block_action.triggered.connect(self.insert_code_block)
        self.markdown_toolbar.addAction(code_block_action)
        
        self.markdown_toolbar.addSeparator()
        
        list_action = QAction("• Lista", self)
        list_action.setToolTip("Lista nieuporządkowana")
        list_action.triggered.connect(self.insert_list)
        self.markdown_toolbar.addAction(list_action)
        
        numbered_list_action = QAction("1. Lista", self)
        numbered_list_action.setToolTip("Lista numerowana")
        numbered_list_action.triggered.connect(self.insert_numbered_list)
        self.markdown_toolbar.addAction(numbered_list_action)
        
        self.markdown_toolbar.addSeparator()
        
        table_action = QAction("📊", self)
        table_action.setToolTip("Wstaw tabelę")
        table_action.triggered.connect(self.insert_table)
        self.markdown_toolbar.addAction(table_action)
        
        quote_action = QAction("❝", self)
        quote_action.setToolTip("Cytat")
        quote_action.triggered.connect(self.insert_quote)
        self.markdown_toolbar.addAction(quote_action)
        
        hr_action = QAction("—", self)
        hr_action.setToolTip("Linia pozioma")
        hr_action.triggered.connect(self.insert_horizontal_rule)
        self.markdown_toolbar.addAction(hr_action)
        
        # Zbierz wszystkie akcje
        self.toolbar_actions = list(self.markdown_toolbar.actions())
        
        # Dodaj separator i przycisk overflow na końcu
        self.overflow_button = QToolButton()
        self.overflow_button.setText("⋯")
        self.overflow_button.setToolTip("Więcej opcji")
        self.overflow_button.setPopupMode(QToolButton.InstantPopup)
        self.overflow_button.setStyleSheet("QToolButton { font-weight: bold; font-size: 14px; padding: 5px 8px; }")
        self.overflow_menu = QMenu()
        self.overflow_button.setMenu(self.overflow_menu)
        self.overflow_button.setVisible(False)
        self.overflow_action = self.markdown_toolbar.addWidget(self.overflow_button)
    
    def set_view_mode(self, mode):
        self.view_mode = mode
        
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            tab.set_view_mode(mode)
        
        self.update_preview()
        
        mode_names = ["Tylko kod", "Podzielony widok", "Tylko podgląd"]
        self.statusBar().showMessage(f"Tryb widoku: {mode_names[mode]}", 2000)
    
    def insert_markdown(self, before, after):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            cursor.insertText(before + selected_text + after)
        else:
            cursor.insertText(before + after)
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(after))
            editor.setTextCursor(cursor)
    
    def insert_heading(self, level):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.StartOfLine)
        prefix = '#' * level + ' '
        cursor.insertText(prefix)
    
    def insert_link(self):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f'[{text}](url)')
        else:
            cursor.insertText('[tekst](url)')
    
    def insert_image(self):
        editor = self.get_current_editor()
        if not editor:
            return
        
        # Dialog wyboru pliku obrazu
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Wybierz obrazek", "",
            "Obrazy (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;Wszystkie pliki (*)"
        )
        
        if file_name:
            cursor = editor.textCursor()
            # Dla lokalnych plików używamy ścieżki bezwzględnej
            if cursor.hasSelection():
                alt_text = cursor.selectedText()
            else:
                alt_text = Path(file_name).stem
            cursor.insertText(f'![{alt_text}]({file_name})')
    
    def insert_code_block(self):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            selected_text = selected_text.replace('\u2029', '\n')
            cursor.insertText(f'```\n{selected_text}\n```')
        else:
            cursor.insertText('```\n\n```')
            cursor.movePosition(QTextCursor.Up)
            editor.setTextCursor(cursor)
    
    def insert_list(self):
        editor = self.get_current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')
            bulleted_lines = ['- ' + line for line in lines]
            cursor.insertText('\n'.join(bulleted_lines))
        else:
            cursor.movePosition(QTextCursor.StartOfLine)
            cursor.insertText('- ')
    
    def insert_numbered_list(self):
        editor = self.get_current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')
            numbered_lines = []
            for i, line in enumerate(lines, 1):
                numbered_lines.append(f'{i}. {line}')
            cursor.insertText('\n'.join(numbered_lines))
        else:
            cursor.movePosition(QTextCursor.StartOfLine)
            cursor.insertText('1. ')
    
    def insert_table(self):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        table = '\n| Kolumna | Kolumna | Kolumna |\n'
        table += '|:---------:|:---------:|:----------:|\n'
        table += '| Komórka | Komórka | Komórka |\n'
        table += '| Komórka | Komórka | Komórka |\n'
        cursor.insertText(table)
    
    def insert_quote(self):
        editor = self.get_current_editor()
        if not editor:
            return
        
        cursor = editor.textCursor()
        
        if cursor.hasSelection():
            # Pobierz zaznaczony tekst i dodaj > do każdej linii
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            
            # Rozszerz zaznaczenie do pełnych linii
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.StartOfBlock)
            start = cursor.position()
            
            cursor.setPosition(end)
            cursor.movePosition(QTextCursor.EndOfBlock)
            end = cursor.position()
            
            # Zaznacz pełne linie
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            
            selected_text = cursor.selectedText()
            lines = selected_text.split('\u2029')  # Qt używa tego jako separatora linii
            quoted_lines = ['> ' + line for line in lines]
            cursor.insertText('\n'.join(quoted_lines))
        else:
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.insertText('> ')
    
    def insert_horizontal_rule(self):
        editor = self.get_current_editor()
        if not editor:
            return
            
        cursor = editor.textCursor()
        cursor.insertText('\n---\n')
            
    def open_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Otwórz plik", "",
            "Pliki tekstowe (*.txt *.md);;Wszystkie pliki (*)"
        )
        if file_name:
            self.load_file(file_name)
            
    def save_file(self):
        tab = self.get_current_tab()
        if not tab:
            return
            
        if not tab.file_path:
            self.save_file_as()
        else:
            self.write_file(tab.file_path)
            
    def save_file_as(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Zapisz plik jako", "",
            "Pliki tekstowe (*.txt);;Pliki Markdown (*.md)"
        )
        if file_name:
            self.write_file(file_name)
            
    def toggle_dark_mode(self):
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()
        self.save_settings()
        self.update_preview()
            
    def choose_font(self):
        editor = self.get_current_editor()
        if not editor:
            return
            
        ok, font = QFontDialog.getFont(editor.font(), self)
        if ok:
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                tab.text_edit.setFont(font)
            self.save_settings()
            
    def set_font_size(self, size):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            font = tab.text_edit.font()
            font.setPointSize(size)
            tab.text_edit.setFont(font)
        self.save_settings()
        
    def customize_colors(self):
        mode = 'dark' if self.is_dark_mode else 'light'
        current_colors = self.color_scheme.dark.copy() if self.is_dark_mode else self.color_scheme.light.copy()
        
        # Usuń kolory Markdown z tego dialogu
        for key in list(current_colors.keys()):
            if key.startswith('md_'):
                del current_colors[key]
        
        dialog = ColorCustomizerDialog(current_colors, mode, self)
        if dialog.exec() == QDialog.Accepted:
            new_colors = dialog.get_colors()
            if self.is_dark_mode:
                for key, value in new_colors.items():
                    self.color_scheme.dark[key] = value
            else:
                for key, value in new_colors.items():
                    self.color_scheme.light[key] = value
            self.apply_theme()
            self.save_settings()
    
    def customize_markdown_styles(self):
        mode = 'dark' if self.is_dark_mode else 'light'
        current_colors = self.color_scheme.dark if self.is_dark_mode else self.color_scheme.light
        
        dialog = MarkdownStyleDialog(current_colors, mode, self)
        dialog.set_font_settings(self.md_font_family, self.md_font_size)
        
        if dialog.exec() == QDialog.Accepted:
            new_colors = dialog.get_colors()
            font_settings = dialog.get_font_settings()
            
            self.md_font_family = font_settings['family']
            self.md_font_size = font_settings['size']
            
            if self.is_dark_mode:
                self.color_scheme.dark = new_colors
            else:
                self.color_scheme.light = new_colors
            
            self.save_settings()
            self.update_preview()
            self.statusBar().showMessage("Style Markdown zaktualizowane", 2000)
        
    def update_preview(self):
        tab = self.get_current_tab()
        if not tab:
            return
            
        if tab.view_mode != 0:
            # Zapisz pozycję scrollbara
            scrollbar = tab.preview.verticalScrollBar()
            scroll_pos = scrollbar.value()
            scroll_max = scrollbar.maximum()
            
            markdown = tab.get_content()
            colors = self.color_scheme.dark if self.is_dark_mode else self.color_scheme.light
            html = MarkdownConverter.to_html(markdown, colors, self.md_font_family, self.md_font_size)
            
            # Wyłącz aktualizacje podczas zmiany HTML aby uniknąć ghostingu
            tab.preview.setUpdatesEnabled(False)
            tab.preview.setHtml(html)
            
            # Przywróć pozycję scrollbara po małym opóźnieniu
            def restore_scroll():
                if scroll_max > 0:
                    # Proporcjonalne przywrócenie pozycji
                    new_max = scrollbar.maximum()
                    if new_max > 0:
                        ratio = scroll_pos / scroll_max
                        scrollbar.setValue(int(ratio * new_max))
                    else:
                        scrollbar.setValue(scroll_pos)
                else:
                    scrollbar.setValue(scroll_pos)
                # Włącz z powrotem aktualizacje
                tab.preview.setUpdatesEnabled(True)
            
            QTimer.singleShot(10, restore_scroll)
            
    def load_file(self, file_name):
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for i in range(self.tab_widget.count()):
                tab = self.tab_widget.widget(i)
                if tab.file_path == file_name:
                    self.tab_widget.setCurrentIndex(i)
                    return
            
            current_tab = self.get_current_tab()
            if current_tab and not current_tab.file_path and not current_tab.is_modified():
                tab = current_tab
            else:
                tab = self.new_file()
            
            tab.set_content(content)
            tab.file_path = file_name
            tab.set_modified(False)
            
            index = self.tab_widget.indexOf(tab)
            self.tab_widget.setTabText(index, Path(file_name).name)
            
            # Ustaw domyślny tryb widoku (dla .md osobny)
            if file_name.lower().endswith('.md'):
                tab.set_view_mode(self.md_default_view_mode)
            else:
                tab.set_view_mode(self.default_view_mode)
            
            self.update_window_title()
            self.statusBar().showMessage(f"Wczytano: {file_name}", 2000)
            self.update_preview()
            
        except Exception as e:
            QMessageBox.warning(self, "Błąd", f"Nie można otworzyć pliku:\n{str(e)}")
            
    def write_file(self, file_name):
        tab = self.get_current_tab()
        if not tab:
            return
            
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write(tab.get_content())
            
            tab.file_path = file_name
            tab.set_modified(False)
            
            index = self.tab_widget.indexOf(tab)
            self.tab_widget.setTabText(index, Path(file_name).name)
            
            self.update_window_title()
            self.statusBar().showMessage(f"Zapisano: {file_name}", 2000)
            
        except Exception as e:
            QMessageBox.warning(self, "Błąd", f"Nie można zapisać pliku:\n{str(e)}")
        
    def apply_theme(self):
        colors = self.color_scheme.dark if self.is_dark_mode else self.color_scheme.light
        
        # Aktualizuj TabBar
        self.custom_tab_bar.set_dark_mode(self.is_dark_mode)
        
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            tab.text_edit.set_dark_mode(self.is_dark_mode)
        
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(colors['window']))
        palette.setColor(QPalette.WindowText, QColor(colors['text']))
        palette.setColor(QPalette.Base, QColor(colors['base']))
        palette.setColor(QPalette.AlternateBase, QColor(colors['button']))
        palette.setColor(QPalette.Text, QColor(colors['text']))
        palette.setColor(QPalette.Button, QColor(colors['button']))
        palette.setColor(QPalette.ButtonText, QColor(colors['text']))
        palette.setColor(QPalette.Highlight, QColor(colors['highlight']))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        palette.setColor(QPalette.ToolTipBase, QColor(colors['button']))
        palette.setColor(QPalette.ToolTipText, QColor(colors['text']))
        
        if self.is_dark_mode:
            palette.setColor(QPalette.Light, QColor(60, 60, 60))
            palette.setColor(QPalette.Midlight, QColor(50, 50, 50))
            palette.setColor(QPalette.Dark, QColor(35, 35, 35))
            palette.setColor(QPalette.Mid, QColor(40, 40, 40))
            palette.setColor(QPalette.Shadow, QColor(20, 20, 20))
        else:
            palette.setColor(QPalette.Light, QColor(255, 255, 255))
            palette.setColor(QPalette.Midlight, QColor(240, 240, 240))
            palette.setColor(QPalette.Dark, QColor(160, 160, 160))
            palette.setColor(QPalette.Mid, QColor(200, 200, 200))
            palette.setColor(QPalette.Shadow, QColor(100, 100, 100))
        
        QApplication.instance().setPalette(palette)
        
        if self.is_dark_mode:
            style = f"""
                QMenu {{ background-color: #2d2d2d; color: #d4d4d4; border: 1px solid #404040; }}
                QMenu::item:selected {{ background-color: {colors['highlight']}; color: white; }}
                QMenuBar {{ background-color: #1e1e1e; color: #d4d4d4; }}
                QMenuBar::item:selected {{ background-color: {colors['highlight']}; color: white; }}
                QToolBar {{ background-color: #2d2d2d; border-bottom: 1px solid #404040; spacing: 3px; padding: 3px; }}
                QToolButton {{ background-color: #3d3d3d; color: #d4d4d4; border: 1px solid #555555; border-radius: 3px; padding: 5px 10px; margin: 2px; }}
                QToolButton:hover {{ background-color: #4d4d4d; border: 1px solid {colors['highlight']}; }}
                QToolButton:pressed {{ background-color: {colors['highlight']}; }}
                QTabWidget::pane {{ border: 1px solid #404040; }}
                QTabBar::tab {{ background-color: #2d2d2d; color: #d4d4d4; padding: 8px 30px 8px 12px; border: 1px solid #404040; border-bottom: none; margin-right: 2px; }}
                QTabBar::tab:selected {{ background-color: #3d3d3d; border-bottom: 2px solid {colors['highlight']}; }}
                QTabBar::tab:hover {{ background-color: #3d3d3d; }}
            """
        else:
            style = f"""
                QMenu {{ background-color: white; color: black; border: 1px solid #cccccc; }}
                QMenu::item:selected {{ background-color: {colors['highlight']}; color: white; }}
                QMenuBar {{ background-color: #f0f0f0; color: black; }}
                QMenuBar::item:selected {{ background-color: {colors['highlight']}; color: white; }}
                QToolBar {{ background-color: #f8f8f8; border-bottom: 1px solid #cccccc; spacing: 3px; padding: 3px; }}
                QToolButton {{ background-color: #ffffff; color: #000000; border: 1px solid #cccccc; border-radius: 3px; padding: 5px 10px; margin: 2px; }}
                QToolButton:hover {{ background-color: #e8f4fd; border: 1px solid {colors['highlight']}; }}
                QToolButton:pressed {{ background-color: {colors['highlight']}; color: white; }}
                QTabWidget::pane {{ border: 1px solid #cccccc; }}
                QTabBar::tab {{ background-color: #e8e8e8; color: #000000; padding: 8px 30px 8px 12px; border: 1px solid #cccccc; border-bottom: none; margin-right: 2px; }}
                QTabBar::tab:selected {{ background-color: #ffffff; border-bottom: 2px solid {colors['highlight']}; }}
                QTabBar::tab:hover {{ background-color: #f0f0f0; }}
            """
        self.setStyleSheet(style)
        
    def load_settings(self):
        self.is_dark_mode = self.settings.value('dark_mode', False, type=bool)
        self.scroll_lines = self.settings.value('scroll_lines', 1, type=int)
        self.view_mode = self.settings.value('view_mode', 1, type=int)
        self.md_font_family = self.settings.value('md_font_family', 'system-ui', type=str)
        self.md_font_size = self.settings.value('md_font_size', 16, type=int)
        self.default_view_mode = self.settings.value('default_view_mode', 1, type=int)
        self.md_default_view_mode = self.settings.value('md_default_view_mode', 1, type=int)
        self.duplicate_with_newline = self.settings.value('duplicate_with_newline', True, type=bool)
        
        shortcuts_str = self.settings.value('shortcuts', '')
        if shortcuts_str:
            try:
                self.shortcuts = json.loads(shortcuts_str)
            except:
                pass
        
        light_colors_str = self.settings.value('light_colors', '')
        if light_colors_str:
            try:
                self.color_scheme.light = json.loads(light_colors_str)
            except:
                pass
        dark_colors_str = self.settings.value('dark_colors', '')
        if dark_colors_str:
            try:
                self.color_scheme.dark = json.loads(dark_colors_str)
            except:
                pass
        
    def save_settings(self):
        self.settings.setValue('dark_mode', self.is_dark_mode)
        self.settings.setValue('scroll_lines', self.scroll_lines)
        self.settings.setValue('view_mode', self.view_mode)
        self.settings.setValue('shortcuts', json.dumps(self.shortcuts))
        self.settings.setValue('md_font_family', self.md_font_family)
        self.settings.setValue('md_font_size', self.md_font_size)
        self.settings.setValue('default_view_mode', self.default_view_mode)
        self.settings.setValue('md_default_view_mode', self.md_default_view_mode)
        self.settings.setValue('duplicate_with_newline', self.duplicate_with_newline)
        
        editor = self.get_current_editor()
        if editor:
            font = editor.font()
            self.settings.setValue('font_family', font.family())
            self.settings.setValue('font_size', font.pointSize())
        
        self.settings.setValue('light_colors', json.dumps(self.color_scheme.light))
        self.settings.setValue('dark_colors', json.dumps(self.color_scheme.dark))
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Odroczona aktualizacja aby layout zdążył się przeliczyć
        QTimer.singleShot(50, self.update_toolbar_overflow)
    
    def update_toolbar_overflow(self):
        """Aktualizuj widoczność przycisków paska i menu overflow"""
        if not hasattr(self, 'toolbar_actions') or not self.toolbar_actions:
            return
        
        if not hasattr(self, 'overflow_button'):
            return
        
        toolbar_width = self.markdown_toolbar.width()
        if toolbar_width < 100:  # Toolbar jeszcze nie zainicjalizowany
            return
        
        overflow_btn_width = 60
        available_width = toolbar_width - overflow_btn_width - 10
        
        # Najpierw pokaż wszystkie akcje
        for action in self.toolbar_actions:
            action.setVisible(True)
        
        # Wymuś aktualizację layoutu
        self.markdown_toolbar.updateGeometry()
        QApplication.processEvents()
        
        # Zmierz i ukryj te które się nie mieszczą
        current_width = 0
        hidden_actions = []
        
        for action in self.toolbar_actions:
            widget = self.markdown_toolbar.widgetForAction(action)
            if widget:
                action_width = widget.sizeHint().width() + 6
                
                if current_width + action_width > available_width:
                    hidden_actions.append(action)
                    action.setVisible(False)
                else:
                    current_width += action_width
            else:
                # Separator lub inna akcja bez widgetu
                current_width += 10
        
        # Aktualizuj menu overflow
        self.overflow_menu.clear()
        
        if hidden_actions:
            self.overflow_button.setVisible(True)
            for action in hidden_actions:
                if action.isSeparator():
                    self.overflow_menu.addSeparator()
                else:
                    menu_action = QAction(action.text(), self)
                    menu_action.setToolTip(action.toolTip())
                    # Połącz bezpośrednio z oryginalną akcją
                    menu_action.triggered.connect(lambda checked, a=action: a.trigger())
                    self.overflow_menu.addAction(menu_action)
        else:
            self.overflow_button.setVisible(False)
    
    def closeEvent(self, event):
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if tab.is_modified():
                self.tab_widget.setCurrentIndex(i)
                reply = QMessageBox.question(
                    self, "Potwierdź",
                    f"Dokument '{self.tab_widget.tabText(i).rstrip('*')}' został zmodyfikowany.\nCzy chcesz zapisać zmiany?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
                )
                
                if reply == QMessageBox.Save:
                    self.save_file()
                elif reply == QMessageBox.Cancel:
                    event.ignore()
                    return
        
        self.save_settings()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("UniPad++")
    editor = TextEditor()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()