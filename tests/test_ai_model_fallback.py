import ai


def test_python_groq_model_fallback_is_bounded(monkeypatch):
    calls = []
    ai.init(None, {'AI Groq 호출 간격(초)': 0})
    class Response:
        status_code = 404
        def json(self): return {'error': {'code': 'model_not_found'}}
    def post(*args, **kwargs):
        calls.append(kwargs['json']['model'])
        return Response()
    monkeypatch.setattr(ai.requests, 'post', post)
    provider = dict(name='groq', key='TEST_UNUSED', url='https://unused.invalid')
    assert ai._post(provider, '/chat/completions', {'model': 'missing'}, 'test') is None
    assert calls == ['missing', 'openai/gpt-oss-20b']

