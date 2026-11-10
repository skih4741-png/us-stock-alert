import smtplib
import notify


def configure(monkeypatch):
    for key, value in dict(MAIL_ENABLED='1', NAVER_ID=' sample ', NAVER_APP_PASSWORD=' secret ').items():
        monkeypatch.setenv(key,value)
    monkeypatch.delenv('MAIL_TO',raising=False)
    monkeypatch.delenv('SMTP_HOST',raising=False)


def test_default_recipient_uses_normalized_full_address(monkeypatch):
    configure(monkeypatch)
    calls=[]
    class SMTP:
        def __init__(self,*a,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def login(self,*args): calls.append(args)
        def sendmail(self, sender, recipients, msg):
            assert sender=='sample@naver.com' and recipients==[sender]
            assert 'To: sample@naver.com' in msg
            return {}
    monkeypatch.setattr(notify.smtplib,'SMTP_SSL',SMTP)
    assert notify.send_mail('test','text')
    assert calls==[('sample@naver.com','secret')]
    assert notify.MAIL_RESULT['code']=='accepted'


def test_authentication_error_is_actionable_without_credentials(monkeypatch,caplog):
    configure(monkeypatch)
    def fail(*a,**k): raise smtplib.SMTPAuthenticationError(535,b'private-provider-secret')
    monkeypatch.setattr(notify.smtplib,'SMTP_SSL',fail)
    assert not notify.send_mail('test','text')
    assert notify.MAIL_RESULT['code']=='authentication'
    assert '535' in notify.MAIL_RESULT['detail']
    assert 'private-provider-secret' not in caplog.text


def test_disabled_and_missing_configuration_are_distinct(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv('MAIL_ENABLED','0')
    assert not notify.send_mail('test','text')
    assert notify.MAIL_RESULT['code']=='disabled'
    monkeypatch.setenv('MAIL_ENABLED','1')
    monkeypatch.delenv('NAVER_APP_PASSWORD')
    assert not notify.send_mail('test','text')
    assert notify.MAIL_RESULT['code']=='missing_config'
