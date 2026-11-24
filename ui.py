"""Rounded, anti-aliased Tk widgets drawn on canvases (cards, buttons, pills, inputs)."""

import sys
import tkinter as tk
from tkinter import font as tkfont

MACOS = sys.platform == "darwin"
FONT = "Helvetica Neue" if MACOS else "Segoe UI Variable Text"
DISPLAY = "Helvetica Neue" if MACOS else "Segoe UI Variable Display"
MONO = "Menlo" if MACOS else "Cascadia Mono"

_CORNERS = {}


def _rgb(widget, color):
    return tuple(value / 257 for value in widget.winfo_rgb(color))


def _mix(colors_weights):
    channels = [sum(c[i] * w for c, w in colors_weights) for i in range(3)]
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in channels)


def corner(widget, radius, fill, border, outside, quadrant):
    """An anti-aliased quarter circle (fill + 1 px border) blended onto `outside`."""
    key = (id(widget._root()), radius, fill, border, outside, quadrant)
    if key in _CORNERS:
        return _CORNERS[key]
    f, b, o = _rgb(widget, fill), _rgb(widget, border or fill), _rgb(widget, outside)
    samples = 4
    rows = []
    for j in range(radius):
        row = []
        for i in range(radius):
            outer = inner = 0
            for sy in range(samples):
                for sx in range(samples):
                    x = i + (sx + 0.5) / samples
                    y = j + (sy + 0.5) / samples
                    d = ((radius - x) ** 2 + (radius - y) ** 2) ** 0.5
                    outer += d <= radius
                    inner += d <= radius - 1
            outer /= samples * samples
            inner /= samples * samples
            row.append(_mix(((o, 1 - outer), (b, outer - inner), (f, inner))))
        rows.append(row)
    if quadrant in ("tr", "br"):
        rows = [list(reversed(r)) for r in rows]
    if quadrant in ("bl", "br"):
        rows = list(reversed(rows))
    image = tk.PhotoImage(master=widget, width=radius, height=radius)
    image.put(" ".join("{" + " ".join(r) + "}" for r in rows))
    _CORNERS[key] = image
    return image


def round_rect(canvas, width, height, radius, fill, border=None, outside=None, tag="shape"):
    """Draw a rounded rectangle filling the canvas area (0, 0, width, height)."""
    canvas.delete(tag)
    if width < 2 or height < 2:
        return
    radius = max(2, min(radius, width // 2, height // 2))
    outside = outside or canvas.cget("bg")
    edge = border or fill
    r = radius
    canvas.create_rectangle(r, 0, width - r, height, fill=fill, outline="", tags=tag)
    canvas.create_rectangle(0, r, width, height - r, fill=fill, outline="", tags=tag)
    if border:
        canvas.create_line(r, 0, width - r, 0, fill=edge, tags=tag)
        canvas.create_line(r, height - 1, width - r, height - 1, fill=edge, tags=tag)
        canvas.create_line(0, r, 0, height - r, fill=edge, tags=tag)
        canvas.create_line(width - 1, r, width - 1, height - r, fill=edge, tags=tag)
    for quadrant, x, y in (("tl", 0, 0), ("tr", width - r, 0), ("bl", 0, height - r),
                           ("br", width - r, height - r)):
        canvas.create_image(x, y, image=corner(canvas, r, fill, border, outside, quadrant),
                            anchor="nw", tags=tag)
    canvas.tag_lower(tag)


class RoundFrame(tk.Frame):
    """A rounded card: a plain frame with rounded-corner images laid over its four corners.

    Widgets embedded in a canvas stop repainting on macOS after their page is hidden and shown,
    so the card itself holds the content. Put children in `.inner` (the card itself).
    """

    def __init__(self, parent, fill="#ffffff", border=None, radius=14, padding=18, expand=False):
        super().__init__(parent, bg=fill, bd=0, highlightthickness=1 if border else 0,
                         highlightbackground=border or fill, highlightcolor=border or fill,
                         padx=max(0, padding - (1 if border else 0)), pady=max(0, padding - (1 if border else 0)))
        self.fill, self.border, self.radius = fill, border, radius
        self.outside = parent.cget("bg")
        self.inner = self
        self.corners = []
        for quadrant, anchor, x, y in (("tl", "nw", 0, 0), ("tr", "ne", 1, 0), ("bl", "sw", 0, 1), ("br", "se", 1, 1)):
            piece = tk.Label(self, bd=0, highlightthickness=0, bg=self.outside)
            piece.place(relx=x, rely=y, anchor=anchor, bordermode="outside")
            piece.quadrant = quadrant
            self.corners.append(piece)
        self.paint()
        self.bind("<Configure>", lambda _: self.lift_corners())
        self.after(60, self.lift_corners)

    def paint(self):
        for piece in self.corners:
            piece.configure(image=corner(self, self.radius, self.fill, self.border, self.outside, piece.quadrant))

    def lift_corners(self):
        # Children added after the corners would otherwise cover them.
        for piece in self.corners:
            piece.lift()

    def recolor(self, fill, border=None):
        self.fill, self.border = fill, border
        self.configure(bg=fill, highlightbackground=border or fill, highlightcolor=border or fill)
        self.paint()


class Pill(tk.Canvas):
    """A small rounded status badge."""

    def __init__(self, parent, text="", fg="#18181b", fill="#f2f2f5", font=None):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.font = tkfont.Font(root=self, font=font or (FONT, 9, "bold"))
        self.set(text, fg, fill)

    def set(self, text, fg, fill, dot=True):
        self.delete("all")
        pad, dot_space = 10, 12 if dot else 0
        width = self.font.measure(text) + 2 * pad + dot_space
        height = self.font.metrics("linespace") + 8
        self.configure(width=width, height=height)
        round_rect(self, width, height, height // 2, fill)
        if dot:
            cy = height / 2
            self.create_oval(pad, cy - 3.5, pad + 7, cy + 3.5, fill=fg, outline="")
        self.create_text(pad + dot_space, height / 2, text=text, fill=fg, font=self.font, anchor="w")
