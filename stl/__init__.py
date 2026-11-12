"""STL processing (AP5): envelope, feature detection, defeaturing.

Pipeline (HANDOFF 3.7):
    mesh  = io.load_stl(path, unit="mm")
    env   = envelope.build_envelope(mesh, r_max)
    feats = detect.detect_features(mesh, env)
    out   = defeature.remove_features(mesh, feats, remove_ids)
"""
