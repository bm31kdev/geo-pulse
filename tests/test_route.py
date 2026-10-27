from geo_pulse.route import distance_m, points_equidistants

def test_distance_paris():
    assert 900 < distance_m((48.8566,2.3522),(48.8656,2.3522)) < 1100

def test_echantillonnage():
    pts=points_equidistants([(48.8566,2.3522),(48.8666,2.3522)],50)
    assert len(pts)>10 and pts[0]==(48.8566,2.3522) and pts[-1]==(48.8666,2.3522)
