import json
import shutil

import pytest
from PIL import Image

from duplicate_lab.cli import main
from duplicate_lab.visual_set import discover_set, review_set_pair


def dataset(tmp_path):
    root = tmp_path / 'photos'
    root.mkdir()
    image = Image.new('RGB', (100, 60), 'navy')
    image.save(root / 'a.jpg')
    image.resize((50, 30)).save(root / 'b.jpg')
    shutil.copyfile(root / 'a.jpg', root / 'copy.jpg')
    return root


def test_queue_roundtrip_and_immutable_decisions(tmp_path):
    root = dataset(tmp_path)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    output = tmp_path / 'queue'
    assert main(['visual-set', str(root), '--output-dir', str(output)]) == 0
    queue = json.loads((output / 'queue.json').read_text())
    assert len(queue['candidates']) == 2
    assert all(queue['files'][p['left']]['sha256'] != queue['files'][p['right']]['sha256']
               for p in queue['candidates'])
    pair_id = queue['candidates'][0]['id']
    assert main(['visual-set-pair', str(output / 'queue.json'), pair_id,
                 '--output-dir', str(tmp_path / 'accepted'), '--decision', 'accepted_candidate',
                 '--reason', 'Synthetic resized frame']) == 0
    review = json.loads((tmp_path / 'accepted/review.json').read_text())
    assert review['provenance'] == {'queue_id': queue['id'], 'pair_id': pair_id}
    assert review['action_authorized'] is False
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    with pytest.raises(FileExistsError):
        discover_set(root, output)


@pytest.mark.parametrize('change', ['content', 'removed', 'symlink', 'metadata'])
def test_stale_pair_blocked(tmp_path, change):
    root = dataset(tmp_path)
    queue = discover_set(root, tmp_path / 'queue')
    pair = queue['candidates'][0]
    path = root / queue['files'][pair['left']]['path']
    if change == 'content':
        Image.new('RGB', (100, 60), 'red').save(path)
    elif change == 'metadata':
        path.touch()
    else:
        path.unlink()
        if change == 'symlink':
            path.symlink_to(root / 'copy.jpg')
    with pytest.raises((OSError, ValueError)):
        review_set_pair(queue, pair['id'], tmp_path / 'review', 'uncertain', 'check')
    assert not (tmp_path / 'review').exists()


def test_limits_exclusions_and_empty(tmp_path):
    root = dataset(tmp_path)
    with pytest.raises(ValueError, match='arquivos'):
        discover_set(root, tmp_path / 'limited', max_files=2)
    with pytest.raises(ValueError, match='candidatos'):
        discover_set(root, tmp_path / 'limited', max_candidates=1)
    assert not (tmp_path / 'limited').exists()
    (root / 'bad.jpg').write_bytes(b'bad')
    (root / 'link.jpg').symlink_to(root / 'a.jpg')
    queue = discover_set(root, tmp_path / 'queue')
    assert len(queue['excluded']) == 2
    with pytest.raises(ValueError, match='fora'):
        discover_set(root, root / 'output')
    with pytest.raises(ValueError, match='inexistente'):
        review_set_pair(queue, 'invalid', tmp_path / 'review')
    queue['action_authorized'] = True
    with pytest.raises(ValueError, match='inválida'):
        review_set_pair(queue, 'invalid', tmp_path / 'review')
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert discover_set(empty, tmp_path / 'empty-queue')['candidates'] == []


def test_mutation_during_discovery_and_review(tmp_path, monkeypatch):
    import duplicate_lab.visual_review as review_module
    import duplicate_lab.visual_set as module

    root = dataset(tmp_path)
    queue = discover_set(root, tmp_path / 'queue')
    pair = queue['candidates'][0]
    path = root / queue['files'][pair['left']]['path']
    original = review_module._thumbnail

    def mutate(p):
        result = original(p)
        path.touch()
        return result

    monkeypatch.setattr(review_module, '_thumbnail', mutate)
    with pytest.raises((OSError, ValueError)):
        review_set_pair(queue, pair['id'], tmp_path / 'review')
    monkeypatch.setattr(module, '_thumbnail', mutate)
    with pytest.raises((OSError, ValueError)):
        discover_set(root, tmp_path / 'changed')
    assert not (tmp_path / 'changed').exists()


def test_patterned_resize_and_unrelated_frame(tmp_path, patterned_image, noisy_images):
    root = tmp_path / 'photos'
    root.mkdir()
    patterned_image.save(root / 'a.jpg', quality=95)
    patterned_image.resize((192, 128)).save(root / 'b.jpg', quality=70)
    noisy_images[0].save(root / 'unrelated.jpg')
    queue = discover_set(root, tmp_path / 'queue')
    names = [{queue['files'][p[k]]['path'] for k in ('left', 'right')}
             for p in queue['candidates']]
    assert {'a.jpg', 'b.jpg'} in names
    assert all('unrelated.jpg' not in pair for pair in names)
    with pytest.raises(ValueError, match='fora'):
        review_set_pair(queue, queue['candidates'][0]['id'], root / 'nested/review')
