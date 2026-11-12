"""What a launch value starts on this computer (src/app_launch.py). 2026-11-11 reports: "카카오톡 연결해달라는것도
못하는데", "arduino ide 열어줘 … 시스템 경로까지 넣어줬는데 그래도 못함" - the AI had written `arduino`, a folder, a
quoted path, and each failed without a word."""
import os

import pytest

import src.app_launch as al


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A small Windows-like computer: Program Files with two programs, a Start menu with their shortcuts."""
    pf = tmp_path / "Program Files"
    arduino = pf / "Arduino IDE"
    kakao = pf / "Kakao" / "KakaoTalk"
    menu = tmp_path / "ProgramData" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    for d in (arduino, kakao, menu, tmp_path / "home" / "Desktop" / "vspd"):
        d.mkdir(parents=True)
    for f in (arduino / "Arduino IDE.exe", arduino / "Uninstall Arduino IDE.exe", kakao / "KakaoTalk.exe",
              kakao / "CrashReporter.exe", menu / "Arduino IDE.lnk", menu / "카카오톡.lnk",
              tmp_path / "home" / "Desktop" / "memo.txt"):
        f.write_bytes(b"")
    for k, v in (("ProgramFiles", pf), ("ProgramData", tmp_path / "ProgramData"), ("PROGRAMDATA", tmp_path / "ProgramData"),
                 ("USERPROFILE", tmp_path / "home"), ("APPDATA", tmp_path / "none"), ("LOCALAPPDATA", tmp_path / "none"),
                 ("PUBLIC", tmp_path / "none")):
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(al, "_index", (0.0, []))
    monkeypatch.setattr(al, "_app_path", lambda name: "")
    monkeypatch.setattr(al.shutil, "which", lambda name: None)
    return tmp_path


def test_what_the_ai_wrote_is_found_the_way_a_person_would(pc):
    exe = str(pc / "Program Files" / "Arduino IDE" / "Arduino IDE.exe")
    lnk = str(pc / "ProgramData" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Arduino IDE.lnk")
    # a bare name: the Start menu shortcut (the first two requests of the report)
    for said in ("arduino", "arduino ide", "Arduino IDE", "ArduinoIDE.exe"):
        t = al.resolve(said)
        assert (t.kind, t.path) == ("open", lnk), said
    # the program's folder (the third request): the program in it, not an Explorer window
    t = al.resolve(str(pc / "Program Files" / "Arduino IDE"))
    assert (t.kind, t.path) == ("run", exe)
    # the full path, quoted and not, with and without arguments
    assert al.resolve(f'"{exe}"').path == exe and al.resolve(exe).path == exe
    t = al.resolve(f"{exe} --new sketch.ino")
    assert (t.kind, t.path, t.args) == ("run", exe, ["--new", "sketch.ino"])
    # a program with no shortcut of that name: found under Program Files; helpers are not the program
    t = al.resolve("kakaotalk")
    assert (t.kind, t.path) == ("run", str(pc / "Program Files" / "Kakao" / "KakaoTalk" / "KakaoTalk.exe"))
    assert al.resolve("카카오톡").path.endswith("카카오톡.lnk")
    assert al.resolve("uninstall arduino ide").kind == "missing"


def test_folders_documents_and_links_are_opened_and_a_missing_program_is_said(pc):
    t = al.resolve(r"%USERPROFILE%\Desktop\vspd" if os.name == "nt" else "$USERPROFILE/Desktop/vspd")
    assert t.kind == "open" and t.path.endswith("vspd")                         # the user's own folder: opened
    assert al.resolve(str(pc / "home" / "Desktop" / "memo.txt")).kind == "open"
    for link in ("https://www.youtube.com", "ms-settings:display", "kakaotalk://launch"):
        assert (al.resolve(link).kind, al.resolve(link).path) == ("open", link)
    t = al.resolve("photoshop")
    assert not t.ok and "찾지 못했어요" in t.note and "photoshop" in t.note
    assert not al.resolve("").ok and not al.resolve(r"C:\nowhere\thing.exe --x").ok


def test_a_proposal_for_a_program_that_is_not_here_is_refused_and_a_found_one_is_saved_as_its_path(pc, tmp_path):
    from src import llm_binding as lb
    from src.action_bindings import ActionBindingRegistry
    registry = ActionBindingRegistry(tmp_path / "b.json")
    gestures = lb.gesture_list(registry)
    key = gestures[0]["key"]

    def ask(value):
        return lb.check({"summary": "", "questions": [], "proposals": [
            {"gesture_key": key, "app_match": "", "action_type": "launch_app", "action_value": value, "enabled": True,
             "reason": ""}]}, gestures)["proposals"][0]

    row = ask("arduino")
    assert row["ok"] and row["action_value"].strip('"').endswith("Arduino IDE.lnk") and "이 PC에서 찾음" in row["warning"]
    row = ask("photoshop")
    assert not row["ok"] and "찾지 못했어요" in row["problem"]
    assert ask("https://www.youtube.com")["ok"]


def test_the_ai_is_told_not_to_invent_a_gesture_and_to_write_program_names():
    """12:13 that day: "…Arduino IDE.exe 실행" with no hand shape shown became a new "주먹 두 번 집기" gesture, which
    never fired in use (logs/composite_fires has none)."""
    from src import llm_binding as lb
    from src.action_bindings import ActionBindingRegistry
    import inspect
    text = inspect.getsource(lb)
    assert "do not invent" in text and "kakaotalk" in text and "Never invent a path" in text


def test_the_badge_names_the_program_also_for_a_quoted_path_with_spaces(pc):
    from src.action_bindings import format_action_badge
    assert format_action_badge("launch_app", str(pc / "Program Files" / "Arduino IDE")) == "프로그램 실행: Arduino IDE.exe"
    assert format_action_badge("launch_app", str(pc / "home" / "Desktop" / "vspd")) == "폴더 열기: vspd"
    assert format_action_badge("launch_app", r'"C:\Program Files\Arduino IDE\Arduino IDE.exe"') == "프로그램 실행: Arduino IDE.exe"
    assert format_action_badge("launch_app", "chrome.exe --incognito https://www.youtube.com") == "프로그램 실행: chrome.exe"
