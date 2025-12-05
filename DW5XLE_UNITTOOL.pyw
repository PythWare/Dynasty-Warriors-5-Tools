import os
from io import BytesIO
import tkinter as tk
from tkinter import ttk, filedialog

# Paths/constants
ICON_DIR = "DW5XLE_Ico_Files"
BACKUP_DIR = "Backups_For_Mod_Disabling"

# Mod file extension
DW5XLE_UNIT_MOD_EXT = ".dw5xlemod"

# Unit layout
SLOT_SIZE = 22           # 22 bytes per unit
NUM_SLOTS_TOTAL = 895    # 0x37F entries in original script

# AOB pattern used to locate unit block inside the ISO
AOB_PATTERN = (
    b"\x14\x14\x14\x80\x14\x14\x14\x80\x14\x14\x14\x80\x14\x14\x14\x80"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
)


class TheCheck:
    @staticmethod
    def validate_numeric_input(new_value: str) -> bool:
        """
        Accept empty string or non-negative integers only
        Used as TK validatecommand
        """
        if new_value == "":
            return True
        # Only digits, no decimal point
        return new_value.isdigit()


class MainEditor(TheCheck):
    """
    Dynasty Warriors 5 XL/Empires Unit Editor (in-memory)

    Scans iso file for unit data using AOB_PATTERN
    Reads NUM_SLOTS_TOTAL * SLOT_SIZE bytes into a single BytesIO buffer
    Offset for a given slot is: slot_index * SLOT_SIZE
    Only writes two files:
        Backup in BACKUP_DIR (original unit block)
        User-created .dw5xlemod file
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Dynasty Warriors 5 Base/XL/Empires Unit Editor")
        self.root.minsize(1100, 900)
        self.root.resizable(False, False)

        self.dw_iso = ""
        os.makedirs(BACKUP_DIR, exist_ok=True)
        os.makedirs(ICON_DIR, exist_ok=True)

        # Try to set window icon (ignore if missing)
        try:
            self.root.iconbitmap(os.path.join(ICON_DIR, "icon2.ico"))
        except Exception:
            pass

        self.cred = tk.Label(
            self.root,
            text="Credit goes to Michael for documentation of DW5E/DW5XL unit data.",
        )
        self.cred.place(x=0, y=800)

        # Button to open the Mod Manager
        self.editor_button = tk.Button(
            self.root,
            text="Mod Manager",
            command=self.open_mod_manager,
            width=20,
            height=5,
        )
        self.editor_button.place(x=940, y=300)

        self.file_grabber = tk.Button(
            self.root,
            text="Open DW5 XL/E ISO File",
            command=self.ask_file,
            height=5
        )
        self.file_grabber.place(x=940, y=10)

        # In-memory unit data and ISO offset
        self.unit_mem: BytesIO | None = None
        self.iso_unit_offset: int | None = None

        # TK IntVars for fields that appear in the GUI
        self.name = tk.IntVar()        # 2 bytes
        self.unknown1 = tk.IntVar()    # hidden, 1 byte
        self.voice = tk.IntVar()
        self.model = tk.IntVar()
        self.color = tk.IntVar()
        self.moveset = tk.IntVar()
        self.horse = tk.IntVar()
        self.life = tk.IntVar()
        self.attack = tk.IntVar()
        self.defense = tk.IntVar()
        self.bow = tk.IntVar()
        self.mounted = tk.IntVar()
        self.speed = tk.IntVar()
        self.strafespeed = tk.IntVar()
        self.jump = tk.IntVar()
        self.ailevel = tk.IntVar()
        self.aitype = tk.IntVar()
        self.unknown2 = tk.IntVar()    # hidden, 1 byte
        self.weapon = tk.IntVar()
        self.weaponlevel = tk.IntVar()
        self.orb = tk.IntVar()

        self.modname = tk.StringVar()

        # Status label
        self.status_label = tk.Label(self.root, text="", fg="green")
        self.status_label.place(x=10, y=760)

        # Build labels and entries
        self._build_labels()
        self._build_entries()

        # Hex slot selector (0x0-0x37E)
        hex_values = [hex(i) for i in range(NUM_SLOTS_TOTAL)]
        self.selected_slot_str = tk.StringVar(self.root)
        self.selected_slot_str.set(hex_values[0])

        slot_combobox = ttk.Combobox(
            self.root,
            textvariable=self.selected_slot_str,
            values=hex_values,
            width=8,
            state="readonly",
        )
        slot_combobox.bind("<<ComboboxSelected>>", self.slot_selected)
        slot_combobox.place(x=840, y=10)

        tk.Label(self.root, text="Character slot:").place(x=750, y=10)

        # Buttons/mod name input
        tk.Button(
            self.root,
            text="Submit values to unit data",
            command=self.submit_unit,
            height=5,
        ).place(x=300, y=10)

        tk.Button(
            self.root,
            text="Create Unit Mod",
            command=self.create_unit_mod,
            height=5,
            width=20,
        ).place(x=940, y=150)

        tk.Entry(self.root, textvariable=self.modname).place(x=610, y=10)
        tk.Label(self.root, text="Enter a mod name").place(x=500, y=10)

    # Load/backup

    def ask_file(self):
        path = filedialog.askopenfilename(
            title="Select DW5/DW5XL/DW5E ISO File",
            initialdir=os.getcwd(),
            filetypes=[("ISO files", "*.iso")]
        )
        if not path:
            self.status_label.config(text="No file selected.", foreground="orange")
            return
        self.dw_iso = path
        self.status_label.config(
            text=f"Loaded ISO: {os.path.basename(path)}",
            fg="green"
        )
        self._load_unit_data_in_memory()
        # Load initial slot 0
        if self.unit_mem is not None:
            self.unit_display(0)

    def _load_unit_data_in_memory(self):
        """
        Locate the unit data block in the iso and load into BytesIO

        Also creates a backup file in BACKUP_DIR if not present for this ISO
        """

        if not self.dw_iso:
            self.status_label.config(text="No ISO selected.", fg="red")
            return

        if not os.path.isfile(self.dw_iso):
            self.status_label.config(text="Selected ISO not found.", fg="red")
            return

        pattern = AOB_PATTERN
        plen = len(pattern)
        chunk_size = 8000
        found_offset = None
        file_offset = 0

        # First pass: scan for the AOB pattern with overlap to avoid border issues
        with open(self.dw_iso, "rb") as f:
            prev_tail = b""
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break

                data = prev_tail + chunk
                idx = data.find(pattern)
                if idx != -1:
                    # idx is relative to data, which starts at (file_offset - len(prev_tail))
                    absolute = (file_offset - len(prev_tail)) + idx
                    found_offset = absolute + 0x3D0
                    break

                # keep last plen-1 bytes as tail for next iteration
                if len(data) >= plen - 1:
                    prev_tail = data[-(plen - 1):]
                else:
                    prev_tail = data

                file_offset += len(chunk)

        if found_offset is None:
            self.unit_mem = None
            self.iso_unit_offset = None
            self.status_label.config(
                text="Could not locate unit data block in ISO file.",
                fg="red",
            )
            return

        # Second pass (or reopen) to read the unit block itself
        with open(self.dw_iso, "rb") as f:
            self.iso_unit_offset = found_offset
            f.seek(found_offset)
            total_bytes = SLOT_SIZE * NUM_SLOTS_TOTAL
            data = f.read(total_bytes)

        if len(data) != total_bytes:
            self.unit_mem = None
            self.iso_unit_offset = None
            self.status_label.config(
                text=(
                    f"Unexpected EOF: wanted {total_bytes} bytes of unit data, "
                    f"got {len(data)}"
                ),
                fg="red",
            )
            return

        # Store in-memory
        self.unit_mem = BytesIO(data)

        # Create backup once per ISO
        iso_base = os.path.splitext(os.path.basename(self.dw_iso))[0]
        backup_name = f"{iso_base}_Original.unitdata"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            with open(backup_path, "wb") as bf:
                bf.write(data)

        self.status_label.config(
            text="Unit block loaded into memory and backup created (if missing).",
            fg="green",
        )

    # GUI building helpers

    def _build_labels(self):
        labels = [
            "Name",
            "Voice",
            "Model",
            "Color",
            "Moveset",
            "Horse",
            "Life",
            "Attack Stat",
            "Defense Stat",
            "Bow",
            "Mounted",
            "Speed",
            "Strafe Speed",
            "Jump",
            "AI Level",
            "AI Type",
            "Weapon",
            "Weapon Level",
            "Orb",
        ]

        label_x = 160
        base_y = 0
        row_h = 40

        for i, label_text in enumerate(labels):
            y = base_y + i * row_h
            tk.Label(self.root, text=label_text).place(x=label_x, y=y)

    def _build_entries(self):
        vcmd = (self.root.register(self.validate_numeric_input), "%P")

        entry_x = 0
        base_y = 0
        row_h = 40

        vars_in_order = [
            self.name,
            self.voice,
            self.model,
            self.color,
            self.moveset,
            self.horse,
            self.life,
            self.attack,
            self.defense,
            self.bow,
            self.mounted,
            self.speed,
            self.strafespeed,
            self.jump,
            self.ailevel,
            self.aitype,
            self.weapon,
            self.weaponlevel,
            self.orb,
        ]

        for i, var in enumerate(vars_in_order):
            y = base_y + i * row_h
            tk.Entry(
                self.root,
                textvariable=var,
                validate="key",
                validatecommand=vcmd,
            ).place(x=entry_x, y=y)

    # Slot handling

    def _get_selected_slot_index(self) -> int:
        """
        Parse selected hex string to integer slot index
        """
        slot_str = self.selected_slot_str.get()
        try:
            return int(slot_str, 16)
        except ValueError:
            return 0

    def slot_selected(self, event=None):
        """
        Update display when user chooses a different slot
        """
        index = self._get_selected_slot_index()
        self.unit_display(index)

    # Display/editing

    def unit_display(self, slot_index: int):
        """
        Read one 22 byte record from the in-memory buffer and populate TK IntVars

        Layout (22 bytes):
            0-1 : Name (uint16)
            2   : Unknown1
            3   : Voice
            4   : Model
            5   : Color
            6   : Moveset
            7   : Horse
            8   : Life
            9   : Attack
            10  : Defense
            11  : Bow
            12  : Mounted
            13  : Speed
            14  : Strafe Speed
            15  : Jump
            16  : AI Level
            17  : AI Type
            18  : Unknown2
            19  : Weapon
            20  : Weapon Level
            21  : Orb
        """
        if self.unit_mem is None:
            self.status_label.config(text="Unit data not loaded.", fg="red")
            return

        if not (0 <= slot_index < NUM_SLOTS_TOTAL):
            self.status_label.config(
                text=f"Slot {slot_index} out of range (0–{NUM_SLOTS_TOTAL-1}).",
                fg="red",
            )
            return

        offset = slot_index * SLOT_SIZE
        self.unit_mem.seek(offset)
        data = self.unit_mem.read(SLOT_SIZE)
        if len(data) != SLOT_SIZE:
            self.status_label.config(
                text=f"Unexpected end of unit data at slot {slot_index}.",
                fg="red",
            )
            return

        self.name.set(int.from_bytes(data[0:2], "little"))
        self.unknown1.set(data[2])
        self.voice.set(data[3])
        self.model.set(data[4])
        self.color.set(data[5])
        self.moveset.set(data[6])
        self.horse.set(data[7])
        self.life.set(data[8])
        self.attack.set(data[9])
        self.defense.set(data[10])
        self.bow.set(data[11])
        self.mounted.set(data[12])
        self.speed.set(data[13])
        self.strafespeed.set(data[14])
        self.jump.set(data[15])
        self.ailevel.set(data[16])
        self.aitype.set(data[17])
        self.unknown2.set(data[18])
        self.weapon.set(data[19])
        self.weaponlevel.set(data[20])
        self.orb.set(data[21])

        self.status_label.config(
            text=f"Loaded slot {slot_index} (offset 0x{offset:X}).", fg="green"
        )

    def submit_unit(self):
        """
        Encode current TK IntVars back into the in-memory buffer for the selected slot
        """
        if self.unit_mem is None:
            self.status_label.config(text="Unit data not loaded.", fg="red")
            return

        try:
            slot_index = self._get_selected_slot_index()
            if not (0 <= slot_index < NUM_SLOTS_TOTAL):
                raise ValueError(f"Slot {slot_index} out of range.")

            name_val = self.name.get()
            if not (0 <= name_val <= 0xFFFF):
                raise ValueError("Name ID must be between 0 and 65535.")

            record = bytearray(SLOT_SIZE)
            record[0:2] = name_val.to_bytes(2, "little")

            record[2] = self.unknown1.get() & 0xFF
            record[3] = self.voice.get() & 0xFF
            record[4] = self.model.get() & 0xFF
            record[5] = self.color.get() & 0xFF
            record[6] = self.moveset.get() & 0xFF
            record[7] = self.horse.get() & 0xFF
            record[8] = self.life.get() & 0xFF
            record[9] = self.attack.get() & 0xFF
            record[10] = self.defense.get() & 0xFF
            record[11] = self.bow.get() & 0xFF
            record[12] = self.mounted.get() & 0xFF
            record[13] = self.speed.get() & 0xFF
            record[14] = self.strafespeed.get() & 0xFF
            record[15] = self.jump.get() & 0xFF
            record[16] = self.ailevel.get() & 0xFF
            record[17] = self.aitype.get() & 0xFF
            record[18] = self.unknown2.get() & 0xFF
            record[19] = self.weapon.get() & 0xFF
            record[20] = self.weaponlevel.get() & 0xFF
            record[21] = self.orb.get() & 0xFF

            offset = slot_index * SLOT_SIZE
            self.unit_mem.seek(offset)
            self.unit_mem.write(record)

            self.status_label.config(
                text=f"Values written for slot {slot_index}.", fg="green"
            )

        except Exception as e:
            self.status_label.config(
                text=f"Error with entries: {e}, please use values less than 255.",
                fg="red",
            )

    # Mod file creation

    def create_unit_mod(self):
        """
        Dump current in-memory block to a .dw5xlemod file in the current directory
        """
        if self.unit_mem is None:
            self.status_label.config(text="Unit data not loaded.", fg="red")
            return

        sep = "."
        base_name = self.modname.get().split(sep, 1)[0] or "DW5XLEUnit"
        usermodname = base_name + DW5XLE_UNIT_MOD_EXT

        try:
            data = self.unit_mem.getvalue()
            with open(usermodname, "wb") as f:
                f.write(data)

            self.status_label.config(
                text=f"Mod file '{usermodname}' created successfully.", fg="green"
            )
        except Exception as e:
            self.status_label.config(
                text=f"Error creating mod file '{usermodname}': {e}", fg="red"
            )

    # Mod manager

    def open_mod_manager(self):
        """
        Open a small window with buttons to enable/disable mods on iso file
        """
        if self.iso_unit_offset is None:
            self.status_label.config(
                text="Unit block offset in ISO not available.", fg="red"
            )
            return

        ModManager(self.root, self.dw_iso, self.iso_unit_offset, SLOT_SIZE * NUM_SLOTS_TOTAL)

class ModManager:
    """
    Simple mod manager for DW5XL/E

    Enable Mod: write selected .dw5xlemod block into the iso at the unit offset
    Disable Mod: write selected backup block into the iso at the unit offset
    """

    def __init__(self, parent: tk.Tk, iso_path: str, iso_unit_offset: int, block_size: int):
        self.iso_path = iso_path
        self.iso_unit_offset = iso_unit_offset
        self.block_size = block_size

        self.root = tk.Toplevel(parent)
        self.root.title("DW5XLE Mod Manager")
        self.root.minsize(400, 400)
        self.root.resizable(False, False)

        try:
            self.root.iconbitmap(os.path.join(ICON_DIR, "icon3.ico"))
        except Exception:
            pass

        self.mod_status = tk.Label(self.root, text="", fg="green")
        self.mod_status.place(x=10, y=170)

        tk.Button(
            self.root,
            text="Enable Mod",
            command=self.enable_mod,
            height=10,
            width=50,
        ).place(x=10, y=10)

        tk.Button(
            self.root,
            text="Disable Mod",
            command=self.disable_mod,
            height=10,
            width=50,
        ).place(x=10, y=210)

    def enable_mod(self):
        """
        Ask the user for a .dw5xlemod, then write its contents into the iso
        """
        file_path = filedialog.askopenfilename(
            initialdir=os.getcwd(),
            title="Select mod file",
            filetypes=[("DW5XLE Unit Mods", f"*{DW5XLE_UNIT_MOD_EXT}")]
        )
        if not file_path:
            return

        try:
            with open(file_path, "rb") as f_mod:
                data = f_mod.read()

            if len(data) != self.block_size:
                raise ValueError(
                    f"Mod size {len(data)} bytes does not match expected "
                    f"{self.block_size} bytes."
                )

            with open(self.iso_path, "r+b") as f_iso:
                f_iso.seek(self.iso_unit_offset)
                f_iso.write(data)

            self.mod_status.config(
                text=f"Mod '{os.path.basename(file_path)}' enabled successfully.",
                fg="green",
            )
        except Exception as e:
            self.mod_status.config(text=f"Error enabling mod: {e}", fg="red")

    def disable_mod(self):
        """
        Ask for a backup block and write it back
        """
        file_path = filedialog.askopenfilename(
            initialdir=os.path.join(os.getcwd(), BACKUP_DIR),
            title="Select backup file",
            filetypes=[("DW5XLE Backups", "*.unitdata")]
        )
        if not file_path:
            return

        try:
            with open(file_path, "rb") as f_bak:
                data = f_bak.read()

            if len(data) != self.block_size:
                raise ValueError(
                    f"Backup size {len(data)} bytes does not match expected "
                    f"{self.block_size} bytes."
                )

            with open(self.iso_path, "r+b") as f_iso:
                f_iso.seek(self.iso_unit_offset)
                f_iso.write(data)

            self.mod_status.config(
                text=f"Backup '{os.path.basename(file_path)}' applied successfully.",
                fg="green",
            )
        except Exception as e:
            self.mod_status.config(text=f"Error disabling mod: {e}", fg="red")


def main():
    root = tk.Tk()
    MainEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
