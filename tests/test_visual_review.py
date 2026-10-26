import json

import pytest
from PIL import Image

from duplicate_lab.visual_review import review_pair


def pair(tmp_path):
    source = tmp_path / 'photos'
    source.mkdir()
    left, right = source / 'a.jpg', source / 'b.jpg'
    image = Image.new('RGB', (120, 80), 'navy')
    image.save(left, quality=95)
    image.resize((60, 40)).save(right, quality=65)
    return left, right


def test_resized_pair_and_assessment(tmp_path):
    left, right = pair(tmp_path)
    before = [p.read_bytes() for p in (left, right)]
    output = tmp_path / 'review'
    result = review_pair(left, right, output, 'accepted_candidate', '<human>')
    assert result['binary_equal'] is False
    assert result['capture_identity'] == 'not_established'
    assert result['action_authorized'] is False
    assert result['files'][1]['width'] == 60
    assert json.loads((output / 'review.json').read_text()) == result
    assert '&lt;human&gt;' in (output / 'gallery.html').read_text()
    assert [p.read_bytes() for p in (left, right)] == before
    with pytest.raises(FileExistsError):
        review_pair(left, right, output)


def test_guards(tmp_path):
    left, right = pair(tmp_path)
    with pytest.raises(ValueError, match='motivo'):
        review_pair(left, right, tmp_path / 'review', 'uncertain')
    with pytest.raises(ValueError, match='fora'):
        review_pair(left, right, left.parent / 'review')
    with pytest.raises(ValueError, match='distintos'):
        review_pair(left, left, tmp_path / 'review')
    link = tmp_path / 'link.jpg'
    link.symlink_to(left)
    with pytest.raises(ValueError, match='Links'):
        review_pair(link, right, tmp_path / 'review')
    right.write_bytes(b'not JPEG')
    with pytest.raises(ValueError, match='JPEG'):
        review_pair(left, right, tmp_path / 'review')


def test_mutation_during_preview_blocks_publication(tmp_path, monkeypatch):
    import duplicate_lab.visual_review as module

    left, right = pair(tmp_path)
    original = module._thumbnail

    def mutate(path):
        preview = original(path)
        if path == right:
            Image.new('RGB', (60, 40), 'red').save(right)
        return preview

    monkeypatch.setattr(module, '_thumbnail', mutate)
    output = tmp_path / 'review'
    with pytest.raises(OSError, match='alterado'):
        review_pair(left, right, output)
    assert not output.exists()
