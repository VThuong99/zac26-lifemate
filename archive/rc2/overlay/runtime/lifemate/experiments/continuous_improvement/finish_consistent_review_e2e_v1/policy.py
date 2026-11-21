"""One optional FINISH review; exact repeats never override primary FINISH."""


def eligible(history):
    return all(isinstance(s,dict) and isinstance(s.get('result'),dict)
        and s['result'].get('ok') is True and s['result'].get('done') is not False
        and not s['result'].get('error') and not s['result'].get('waiting_for_user') for s in history)


def select(secondary,history):
    if not isinstance(secondary,dict) or secondary.get('type')!='call':
        return {'type':'finish'}
    if any(secondary==s.get('action') for s in history if isinstance(s,dict)):
        return {'type':'finish'}
    return secondary
