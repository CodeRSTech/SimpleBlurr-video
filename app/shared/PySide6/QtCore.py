from PySide6.QtCore import QPoint, QRect

def qpoint_repr(self: QPoint):
    return f"QPoint({self.x()}, {self.y()})"

def qpoint_str(self: QPoint):
    return f"<QPoint({self.x()}, {self.y()})>"

def qrect_repr(self: QRect):
    return f"QRect({self.x()}, {self.y()}, {self.width()}, {self.height()})"

def qrect_str(self: QRect):
    return f"<QRect({self.x()}, {self.y()}, {self.width()}, {self.height()})>"

QPoint.__repr__ = qpoint_repr
QPoint.__str__ = qpoint_str

QRect.__repr__ = qrect_repr
QRect.__str__ = qrect_str
