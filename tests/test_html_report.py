import json
from pathlib import Path

from conftest import save_jpeg

from duplicate_lab.cli import main
from duplicate_lab.html_report import render_html
from duplicate_lab.models import PairResult, ScanResult
from duplicate_lab.quality import build_quality_report
from duplicate_lab.reporting import validate_output_directory, write_reports
from duplicate_lab.scanner import scan


def _result_with_exact_and_visual(tmp_path: Path, patterned_image) -> ScanResult:
    first = save_jpeg(patterned_image, tmp_path / 'a & "one".jpg')
    (tmp_path / "same.jpg").write_bytes(first.read_bytes())
    save_jpeg(patterned_image, tmp_path / "resized.jpg", quality=70)
    return scan(tmp_path)


def test_html_contains_exact_groups_visual_pairs_and_bounded_thumbnails(
    tmp_path: Path, patterned_image
):
    result = _result_with_exact_and_visual(tmp_path, patterned_image)

    document = render_html(result)

    assert "Grupos exatos" in document
    assert "Candidatos visuais" in document
    assert "Espaço redundante" in document
    assert "A equivalência visual não está confirmada" in document
    assert "data:image/jpeg;base64," in document
    assert "pHash:" in document and "SSIM:" in document and "MAE:" in document


def test_html_escapes_file_names_and_has_no_network_dependency(tmp_path: Path, patterned_image):
    malicious = tmp_path / '<script>alert("x")<script>.jpg'
    save_jpeg(patterned_image, malicious)
    (tmp_path / "duplicate.jpg").write_bytes(malicious.read_bytes())

    document = render_html(scan(tmp_path))

    assert "<script>alert" not in document
    assert "&lt;script&gt;alert" in document
    assert "https://" not in document
    assert "http://" not in document
    assert "connect-src 'none'" in document


def test_html_shows_missing_metrics_and_invalid_files(tmp_path: Path, patterned_image):
    valid = save_jpeg(patterned_image, tmp_path / "valid.jpg")
    invalid = tmp_path / "invalid.jpg"
    invalid.write_bytes(b"not an image")
    base = scan(tmp_path)
    pair = PairResult(
        valid.resolve(), invalid.resolve(), 3, None, None, None, "unclassified", "falha"
    )
    result = ScanResult(base.inventory, base.exact_groups, (pair,))

    document = render_html(result)

    assert "não disponível" in document
    assert "invalid.jpg" in document
    assert "falha" in document
    assert 'data-kind="issue"' in document


def test_output_restriction_no_overwrite_and_original_integrity(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    photo = save_jpeg(patterned_image, source / "original.jpg")
    before = photo.read_bytes()
    result = scan(source)
    output = tmp_path / "reports"

    target = write_reports(result, output, {"html"})[0]

    assert target.is_file()
    assert photo.read_bytes() == before
    try:
        write_reports(result, output, {"html"})
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing report was overwritten without authorization")
    assert photo.read_bytes() == before

    for forbidden in (source, source / "nested"):
        try:
            validate_output_directory(source, forbidden)
        except ValueError:
            pass
        else:
            raise AssertionError("output inside source was accepted")


def test_cli_generates_html(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    save_jpeg(patterned_image, source / "photo.jpg")
    output = tmp_path / "reports"

    exit_code = main(["report", str(source), "--output-dir", str(output), "--format", "html"])

    assert exit_code == 0
    assert (output / "duplicate-lab-gallery.html").is_file()


def test_html_renders_quality_without_recommending_visual_pair(tmp_path: Path, patterned_image):
    result = _result_with_exact_and_visual(tmp_path, patterned_image)
    quality = build_quality_report(result, tmp_path)

    document = render_html(result, quality)

    assert "grupos com avaliação técnica" in document
    assert "identidade binária confirmada" in document
    assert "Nitidez relativa" in document
    assert "equivalência visual não está confirmada" in document


def test_cli_quality_uses_explicit_manifest(tmp_path: Path, patterned_image):
    source = tmp_path / "photos"
    source.mkdir()
    save_jpeg(patterned_image, source / "one.jpg", quality=95)
    save_jpeg(patterned_image, source / "two.jpg", quality=20)
    manifest = tmp_path / "ground-truth.json"
    manifest.write_text(
        json.dumps({"version": 1, "groups": [{"id": "known", "members": ["one.jpg", "two.jpg"]}]}),
        encoding="utf-8",
    )
    output = tmp_path / "reports"

    exit_code = main(
        [
            "report",
            str(source),
            "--output-dir",
            str(output),
            "--format",
            "html",
            "--quality-manifest",
            str(manifest),
        ]
    )

    assert exit_code == 0
    document = (output / "duplicate-lab-gallery.html").read_text(encoding="utf-8")
    assert "known —" in document
    assert "confirmada por manifesto local" in document
    assert "Comparações par a par" in document
    assert "nível 1" in document
