"""已保存回答音訊的讀取與取消狀態。"""

from sqlalchemy import update

from .errors import SourceError
from .storage.tables import VoiceSentence

TIMING_KEYS = ('retrieval_ms', 'answer_ms', 'verification_ms', 'tts_queue_ms', 'tts_synthesis_ms')








def stop(db, turn, status):
    db.execute(update(VoiceSentence).where(VoiceSentence.turn_id==turn.turn_id,VoiceSentence.status.in_(('pending','running'))).values(status=status))




def audio(db, turn_id, index):
    sentence=db.get(VoiceSentence,(turn_id,index))
    if sentence is None:
        raise SourceError('RESOURCE_NOT_FOUND')
    if sentence.status!='ready':
        raise SourceError('VOICE_AUDIO_NOT_READY')
    return sentence.audio
