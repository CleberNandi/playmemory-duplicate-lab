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


def test_content_queue_preserves_locations_and_review_scope(tmp_path):
    root = dataset(tmp_path)
    shutil.copyfile(root / 'b.jpg', root / 'b-copy.jpg')
    output = tmp_path / 'queue'
    assert main(['visual-set', str(root), '--output-dir', str(output),
                 '--collapse-exact', '--max-candidates', '1']) == 0
    queue = json.loads((output / 'queue.json').read_text())
    assert queue['version'] == 2
    assert len(queue['files']) == 4
    assert queue['summary'] == {
        'valid_files': 4, 'unique_binary_contents': 2, 'candidate_location_pairs': 4,
        'review_candidates': 1, 'collapsed_location_pairs': 3,
    }
    pair = queue['candidates'][0]
    assert len(pair['left_members']) == len(pair['right_members']) == 2
    assert set(pair['left_members'] + pair['right_members']) == set(range(4))
    gallery = (output / 'gallery.html').read_text()
    assert all(item['path'] in gallery for item in queue['files'])
    assert main(['visual-set-pair', str(output / 'queue.json'), pair['id'],
                 '--output-dir', str(tmp_path / 'review'), '--decision', 'accepted_candidate',
                 '--reason', 'Synthetic evidence']) == 0
    review = json.loads((tmp_path / 'review/review.json').read_text())
    assert review['provenance']['assessment_scope'] == 'displayed_representatives_only'
    assert len(review['provenance']['observed_locations']) == 4
    assert len(review['files']) == 2
    assert review['action_authorized'] is False


@pytest.mark.parametrize('change', ['content', 'removed', 'symlink'])
def test_content_queue_revalidates_nonrepresentative(tmp_path, change):
    root = dataset(tmp_path)
    queue = discover_set(root, tmp_path / 'queue', collapse_exact=True)
    pair = queue['candidates'][0]
    index = next(i for key in ('left_members', 'right_members') for i in pair[key]
                 if i not in (pair['left'], pair['right']))
    path = root / queue['files'][index]['path']
    if change == 'content':
        path.write_bytes(b'changed')
    else:
        path.unlink()
        if change == 'symlink':
            path.symlink_to(root / 'a.jpg')
    with pytest.raises((OSError, ValueError)):
        review_set_pair(queue, pair['id'], tmp_path / 'review')
    assert not (tmp_path / 'review').exists()


def test_distinct_contents_not_collapsed_even_with_same_phash(tmp_path):
    root = tmp_path / 'photos'
    root.mkdir()
    for index in range(10):
        Image.new('RGB', (100 + index, 60), 'navy').save(root / f'{index}.jpg')
    queue = discover_set(root, tmp_path / 'queue', collapse_exact=True)
    assert queue['summary']['unique_binary_contents'] == 10
    assert queue['summary']['candidate_location_pairs'] == 45
    assert len(queue['candidates']) == 45
    with pytest.raises(ValueError, match='45 revisões, 45 pares'):
        discover_set(root, tmp_path / 'limited', max_candidates=10, collapse_exact=True)
    assert not (tmp_path / 'limited').exists()


def test_binary_repetition_exceeds_old_limit_but_content_mode_fits(tmp_path):
    root = dataset(tmp_path)
    (root / 'copy.jpg').unlink()
    for index in range(10):
        shutil.copyfile(root / 'a.jpg', root / f'a-{index}.jpg')
        shutil.copyfile(root / 'b.jpg', root / f'b-{index}.jpg')
    with pytest.raises(ValueError, match='121 revisões, 121 pares'):
        discover_set(root, tmp_path / 'old')
    queue = discover_set(root, tmp_path / 'new', collapse_exact=True)
    assert queue['summary']['candidate_location_pairs'] == 121
    assert queue['summary']['collapsed_location_pairs'] == 120
    assert len(queue['candidates']) == 1
    assert len(queue['files']) == 22


def test_group_member_changed_during_pair_preview(tmp_path, monkeypatch):
    import duplicate_lab.visual_review as module

    root = dataset(tmp_path)
    queue = discover_set(root, tmp_path / 'queue', collapse_exact=True)
    pair = queue['candidates'][0]
    index = next(i for key in ('left_members', 'right_members') for i in pair[key]
                 if i not in (pair['left'], pair['right']))
    path = root / queue['files'][index]['path']
    thumbnail = module._thumbnail

    def mutate(p):
        result = thumbnail(p)
        path.write_bytes(b'changed')
        return result

    monkeypatch.setattr(module, '_thumbnail', mutate)
    with pytest.raises((OSError, ValueError)):
        review_set_pair(queue, pair['id'], tmp_path / 'review')
    assert not (tmp_path / 'review').exists()
