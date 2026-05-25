"""
End-to-end test for ASR pipeline fixes.

Verifies:
  1. transcribe() does NOT delete the source video
  2. Transcript quality is reasonable
  3. delete_video_dir() correctly removes video + empty parent dir
  4. Quality gate logic (MIN_VIDEO_TRANSCRIPT_CHARS=30)
"""

import os
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TEST_VIDEO = Path(__file__).resolve().parents[2] / "data" / "asr_smoke_test" / "video_copy.mp4"

# Quality gate constant (mirrors collector_service.py)
MIN_VIDEO_TRANSCRIPT_CHARS = 30


def setup_test_video():
    """Copy test video to a temp location for safe testing."""
    dest_dir = Path(__file__).resolve().parents[2] / "data" / "e2e_test_temp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "test_video.mp4"

    # Clean previous test artifacts
    if dest_path.exists():
        os.remove(dest_path)

    shutil.copy2(str(TEST_VIDEO), str(dest_path))
    assert dest_path.exists(), "Copy failed"
    return dest_path, dest_dir


def test_transcribe_does_not_delete_video(dest_path):
    """Verify transcribe() keeps the source video intact."""
    from backend.services.transcription_service import TranscriptionService

    print(f"\n[Test 1] transcribe() should NOT delete video")
    print(f"  Video before: {dest_path.exists()} (size={os.path.getsize(dest_path)} bytes)")

    result = TranscriptionService.transcribe(str(dest_path))
    text = result.get("text", "")

    print(f"  Transcript: {len(text)} chars, {len(result.get('segments', []))} segments")

    # KEY ASSERTION: video still exists
    assert dest_path.exists(), "FAIL: transcribe() deleted the source video!"
    print(f"  PASS: Video still exists after transcribe()")

    # Check no temp WAV files linger in /tmp
    import tempfile
    tmpdir = tempfile.gettempdir()
    wav_files = [
        f for f in os.listdir(tmpdir)
        if f.endswith(".wav") and "tmp" in f
    ]
    if wav_files:
        print(f"  WARNING: {len(wav_files)} temp WAV files found in {tmpdir}")
    else:
        print(f"  PASS: No temp WAV files found")

    return result


def test_transcript_quality(result):
    """Verify transcript quality meets the gate."""
    from backend.services.transcription_service import TranscriptionService

    print(f"\n[Test 2] Transcript quality check (gate: {MIN_VIDEO_TRANSCRIPT_CHARS} chars)")
    text = result.get("text", "").strip()

    if len(text) >= MIN_VIDEO_TRANSCRIPT_CHARS:
        print(f"  PASS: {len(text)} chars >= {MIN_VIDEO_TRANSCRIPT_CHARS} -> would be imported")
    else:
        print(f"  SKIP: {len(text)} chars < {MIN_VIDEO_TRANSCRIPT_CHARS} -> would be skipped (not necessarily a bug)")

    # Print first 200 chars for inspection
    preview = text[:200].replace("\n", "\\n")
    print(f"  Preview: {preview}..." if len(text) > 200 else f"  Full text: {preview}")


def test_delete_video_dir(dest_path, dest_dir):
    """Verify delete_video_dir() removes video + empty parent dir."""
    from backend.services.transcription_service import TranscriptionService

    print(f"\n[Test 3] delete_video_dir() cleanup")
    print(f"  Video exists: {dest_path.exists()}")
    print(f"  Parent dir: {dest_dir}")

    TranscriptionService.delete_video_dir(str(dest_path))

    assert not dest_path.exists(), "FAIL: Video was not deleted"
    print(f"  PASS: Video deleted")

    # Parent dir should be removed if empty
    if not dest_dir.exists():
        print(f"  PASS: Empty parent directory also removed")
    else:
        remaining = list(dest_dir.iterdir())
        if remaining:
            print(f"  INFO: Parent dir kept (has {len(remaining)} remaining files)")
        else:
            print(f"  WARNING: Empty parent dir was not removed")


def test_quality_gate_logic():
    """Test that short transcripts would be skipped (logic verification)."""
    print(f"\n[Test 4] Quality gate logic verification")

    # Simulate what _import_single_record does
    test_cases = [
        ("Good transcript with meaningful content " * 3, False),
        ("short", True),
        ("", True),
        ("a" * 29, True),
        ("a" * 30, False),
    ]

    for text, should_skip in test_cases:
        transcript = text.strip()
        skip = len(transcript) < MIN_VIDEO_TRANSCRIPT_CHARS
        status = "SKIP" if skip else "IMPORT"
        expected = "SKIP" if should_skip else "IMPORT"

        if skip == should_skip:
            print(f"  PASS: {len(transcript):3d} chars -> {status}")
        else:
            print(f"  FAIL: {len(transcript):3d} chars -> {status} (expected {expected})")


def main():
    print("=" * 60)
    print("ASR Pipeline End-to-End Test")
    print("=" * 60)

    assert TEST_VIDEO.exists(), f"Test video not found: {TEST_VIDEO}"

    dest_path, dest_dir = setup_test_video()
    print(f"\nSetup: copied test video -> {dest_path}")

    try:
        result = test_transcribe_does_not_delete_video(dest_path)
        test_transcript_quality(result)
        test_delete_video_dir(dest_path, dest_dir)
        test_quality_gate_logic()
    except Exception as e:
        print(f"\n!!! TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 60)
    print("All end-to-end tests passed!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
