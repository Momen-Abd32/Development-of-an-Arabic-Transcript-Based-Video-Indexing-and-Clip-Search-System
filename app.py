import hashlib
import os
from datetime import date, timedelta
import tempfile
from pathlib import Path

import streamlit as st

from src.media.audio_extractor import AudioExtractor
from src.media.audit_log import AuditLog
from src.media.archive_notes import ArchiveNotes
from src.media.media_catalog import MediaCatalog
from src.media.keyframe_extractor import KeyframeExtractor
from src.media.processing_queue import ProcessingQueue
from src.media.batch_processor import MediaBatchProcessor
from src.media.archive_metrics import ArchiveMetrics
from src.security.auth_manager import AuthManager, AuthRateLimitError
from src.transcription.faster_whisper_engine import FasterWhisperEngine
from src.transcription.transcript_manager import TranscriptManager
from src.transcription.speaker_diarizer import PyannoteSpeakerDiarizer, apply_speaker_turns
from src.transcription.transcript_insights import TranscriptInsights
from src.transcription.transcript_exporter import TranscriptExporter
from src.indexing.indexer import TranscriptIndexer
from src.search.search_engine import SearchEngine, UNSPECIFIED_SPEAKER
from src.search.cross_modal_search import CrossModalSearch
from src.search.archive_qa import ArchiveQA
from src.search.evaluation_dataset import EvaluationDatasetStore
from src.search.cross_modal_evaluation_dataset import CrossModalEvaluationDatasetStore
from src.search.local_answer_provider import OllamaAnswerProvider
from src.search.keyframe_search import KeyframeSearchIndex
from src.search.visual_embedding_provider import SentenceTransformerVisualProvider
from src.search.embedding_provider import SentenceTransformerProvider
from src.clips.clip_manager import ClipManager
from src.clips.clip_metadata import ClipMetadata
from src.clips.clip_exporter import ClipExporter


# --------------------------------------------------
# Configuration
# --------------------------------------------------

MAX_UPLOAD_SIZE_MB = 2048
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def calculate_file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@st.cache_resource
def get_auth_manager() -> AuthManager:
    return AuthManager()


st.set_page_config(
    page_title="فهرسة الفيديو والبحث",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------
# Translations
# --------------------------------------------------

TEXT = {
    "ar": {
        "page_title": "نظام أرشفة وفهرسة الوسائط والبحث في محتواها",
        "login": "تسجيل الدخول",
        "logout": "تسجيل الخروج",
        "username": "اسم المستخدم",
        "password": "كلمة المرور",
        "current_password": "كلمة المرور الحالية",
        "new_password": "كلمة المرور الجديدة",
        "confirm_password": "تأكيد كلمة المرور",
        "signed_in_as": "مسجل الدخول باسم",
        "change_password": "تغيير كلمة المرور",
        "auth_setup_error": "تعذر تهيئة المصادقة: {error}",
        "auth_bootstrap_required": "المصادقة مفعّلة لكن لا يوجد مستخدم إداري. عيّن ARCHIVE_ADMIN_USERNAME وARCHIVE_ADMIN_PASSWORD (كلمة مرور 12 حرفًا على الأقل) ثم أعد تشغيل التطبيق.",
        "login_failed": "اسم المستخدم أو كلمة المرور غير صحيحة.",
        "login_rate_limited": "محاولات دخول كثيرة. حاول لاحقًا.",
        "session_disabled": "تم تعطيل هذا الحساب. سجّل الدخول بحساب آخر.",
        "session_changed": "تم تغيير صلاحيات الحساب أو كلمة مروره. سجّل الدخول مجددًا.",
        "password_changed": "تم تغيير كلمة المرور بنجاح.",
        "password_mismatch": "كلمتا المرور الجديدتان غير متطابقتين.",
        "access_denied": "ليس لديك صلاحية للوصول إلى هذا القسم.",
        "auth_disabled": "إدارة المستخدمين تتطلب تفعيل ARCHIVE_AUTH_ENABLED=true.",
        "user_management_tab": "إدارة المستخدمين",
        "user_management_title": "إدارة حسابات الأرشيف",
        "create_user": "إنشاء مستخدم",
        "display_name": "الاسم الظاهر",
        "select_role": "الدور",
        "role_administrator": "مدير النظام",
        "role_editor": "محرر",
        "role_search_only": "بحث فقط",
        "users": "المستخدمون",
        "active": "نشط",
        "update_user": "تحديث المستخدم",
        "reset_user_password": "إعادة تعيين كلمة المرور",
        "user_created": "تم إنشاء المستخدم.",
        "user_updated": "تم تحديث المستخدم.",
        "user_password_reset": "تمت إعادة تعيين كلمة المرور.",
        "subtitle": "حوّل محتوى الفيديو والتسجيلات الصوتية العربية إلى نص قابل للبحث، واعثر على اللحظات المهمة بسهولة.",
        "language": "اللغة / Language",
        "arabic": "العربية",
        "english": "English",
        "project": "مشروع التخرج",
        "sidebar_title": "القائمة الرئيسية",
        "sidebar_hint": "ارفع فيديو أو ملفاً صوتياً للبدء باستخدام أدوات التفريغ والبحث.",
        "upload_tab": "إضافة وسائط",
        "transcript_tab": "التفريغ النصي",
        "search_tab": "البحث داخل الفيديو",
        "clips_tab": "المقاطع المحفوظة",
        "archive_tab": "إدارة الأرشيف",
        "dashboard_tab": "لوحة المعلومات",
        "audit_tab": "سجل الأحداث",
        "audit_title": "سجل تغييرات الأرشيف والمعالجة",
        "audit_actor": "المنفّذ",
        "audit_entity": "نوع العنصر",
        "audit_all": "الكل",
        "audit_empty": "لا توجد أحداث مسجلة بعد.",
        "audit_details": "تفاصيل التغيير",
        "dashboard_title": "حالة الأرشيف والنظام",
        "dashboard_refresh": "تحديث المؤشرات",
        "dashboard_media": "إجمالي الوسائط",
        "dashboard_videos": "الفيديوهات",
        "dashboard_audio": "التسجيلات الصوتية",
        "dashboard_storage": "حجم الملفات المحفوظة",
        "dashboard_transcripts": "ملفات التفريغ",
        "dashboard_missing": "ملفات مصدر مفقودة",
        "dashboard_status": "حالات المعالجة",
        "dashboard_queue": "حالات قائمة المهام",
        "dashboard_health": "صحة النظام",
        "dashboard_db": "فحص قاعدة البيانات",
        "dashboard_ffmpeg": "FFmpeg",
        "dashboard_whisper": "Faster-Whisper",
        "dashboard_semantic": "البحث الدلالي",
        "dashboard_visual": "البحث البصري",
        "dashboard_diarization": "تمييز المتحدثين",
        "available": "متاح",
        "unavailable": "غير متاح",
        "dashboard_not_initialized": "لم تُنشأ بعد",
        "queue_tab": "قائمة المعالجة",
        "queue_title": "مهام معالجة الوسائط",
        "queue_desc": "أضف مجلدًا إلى قائمة المعالجة الدائمة، ثم نفّذ المهام وأعد المحاولة أو ألغِ المهام المنتظرة.",
        "queue_input": "مسار مجلد الوسائط على الخادم",
        "queue_add": "إضافة مهمة إلى القائمة",
        "queue_added": "تمت إضافة المهمة إلى قائمة المعالجة.",
        "queue_run_next": "تنفيذ المهمة التالية",
        "queue_running": "جاري تنفيذ المهمة...",
        "queue_completed": "اكتملت مهمة المعالجة.",
        "queue_failed": "فشلت المهمة",
        "queue_empty": "لا توجد مهام منتظرة.",
        "queue_recover": "استعادة المهام التي انتهت مهلة تشغيلها (15 دقيقة)",
        "queue_recovered": "عدد المهام المستعادة",
        "queue_cancel": "إلغاء",
        "queue_cancel_requested": "طلب إلغاء المهمة الجارية",
        "queue_retry": "إعادة المحاولة",
        "queue_attempts": "المحاولات",
        "queue_progress": "التقدم",
        "queue_stage": "مرحلة المعالجة",
        "queue_current_file": "الملف الجاري",
        "queue_stage_progress": "تقدم المرحلة",
        "queue_stage_starting": "بدء المهمة",
        "queue_stage_scanning": "فحص المجلد",
        "queue_stage_ready": "اكتمل فحص المجلد",
        "queue_stage_verifying_source": "التحقق من الملف",
        "queue_stage_copying_source": "نسخ الملف إلى الأرشيف",
        "queue_stage_duplicate_skipped": "تجاوز ملف مكرر",
        "queue_stage_checking_transcript": "فحص التفريغ المحفوظ",
        "queue_stage_loading_saved_transcript": "تحميل التفريغ المحفوظ",
        "queue_stage_extracting_audio": "استخراج الصوت",
        "queue_stage_loading_model": "تحميل نموذج التفريغ",
        "queue_stage_transcribing": "تحويل الصوت إلى نص",
        "queue_stage_saving_transcript": "حفظ التفريغ",
        "queue_stage_indexing_transcript": "فهرسة النص",
        "queue_stage_updating_catalog": "تحديث بيانات الأرشيف",
        "queue_stage_file_completed": "اكتمل الملف",
        "queue_stage_file_failed": "فشلت معالجة الملف",
        "queue_stage_retry_wait": "بانتظار إعادة المحاولة",
        "queue_stage_completed": "اكتملت المهمة",
        "queue_stage_cancelled": "أُلغيت المهمة",
        "queue_stage_failed": "فشلت المهمة",
        "queue_stage_queued": "بانتظار التنفيذ",
        "queue_status": "الحالة",
        "queue_path_required": "أدخل مسار مجلد صحيحًا على جهاز تشغيل التطبيق.",
        "queue_note": "يمكن تنفيذ مهمة يدويًا من الواجهة، أو تشغيل عامل مستقل عبر python scripts/run_processing_worker.py لمعالجة المهام دون إبقاء المتصفح مفتوحًا. يمكن طلب إلغاء المهمة الجارية، وستتوقف بعد اكتمال معالجة الملف الحالي.",
        "archive_title": "تنظيم الأرشيف",
        "archive_desc": "نظّم ملفات الوسائط داخل مجموعات وأضف وسومًا لتسهيل إدارتها.",
        "archive_media": "اختر ملفًا من الأرشيف",
        "collection": "المجموعة",
        "collection_placeholder": "مثال: مقابلات إخبارية",
        "tags": "الوسوم",
        "tags_help": "اكتب الوسوم مفصولة بفواصل.",
        "save_archive_metadata": "حفظ بيانات التنظيم",
        "archive_metadata_saved": "تم حفظ المجموعة والوسوم.",
        "filter_collection": "تصفية حسب المجموعة",
        "all_collections": "كل المجموعات",
        "filter_tags": "تصفية حسب الوسوم",
        "archive_items": "ملفات الأرشيف",
        "no_archive_items": "لا توجد ملفات في الأرشيف.",
        "upload_title": "ارفع فيديو أو ملفاً صوتياً",
        "upload_help": "الفيديو: MP4, MKV, MOV, AVI, WEBM | الصوت: MP3, WAV, M4A, AAC, FLAC, OGG — الحد الأقصى 2 GB",
        "choose_video": "اختر ملف فيديو أو صوت",
        "unsupported": "صيغة الملف غير مدعومة.",
        "too_large": "حجم الملف يتجاوز الحد الأقصى البالغ 2 GB.",
        "save_failed": "تعذر حفظ الفيديو",
        "uploaded": "تمت إضافة الملف بنجاح.",
        "file": "الملف",
        "size": "الحجم",
        "video_preview": "معاينة الملف",
        "transcription_title": "التفريغ الصوتي باللغة العربية",
        "transcription_desc": "جهّز الصوت من الفيديو أو الملف الصوتي ثم حوّله إلى نص عربي مع التوقيتات.",
        "start_transcription": "بدء التفريغ",
        "extracting_audio": "جاري استخراج الصوت...",
        "loading_model": "جاري تحميل نموذج Whisper والتفريغ...",
        "transcription_done": "اكتمل التفريغ. عدد المقاطع النصية",
        "transcription_failed": "فشل التفريغ",
        "need_video": "أضف فيديو أو ملفاً صوتياً أولاً حتى تتمكن من استخدام هذه الأدوات.",
        "transcript_title": "مراجعة وتعديل النص",
        "transcript_desc": "راجع المقاطع النصية وعدّل الكلمات عند الحاجة، ثم احفظ التغييرات لإعادة فهرستها.",
        "segment": "المقطع",
        "play_segment": "تشغيل من هذا التوقيت",
        "selected_segment": "معاينة من التوقيت المحدد",
        "diarize_speakers": "تمييز المتحدثين",
        "speaker_diarization_help": "تتطلب هذه الميزة تثبيت requirements-diarization.txt وإعداد HF_TOKEN مع صلاحية الوصول إلى نموذج pyannote. المقاطع التي لا يمكن إسنادها بوضوح ستظهر كمتحدث غير معروف.",
        "diarization_unavailable": "تعذر تشغيل نموذج تمييز المتحدثين؛ تم وضع المقاطع كمتحدث غير معروف بدلاً من إيقاف مراجعة التفريغ.",
        "speaker": "المتحدث",
        "generate_insights": "إنشاء ملخص واستخراج الكلمات المفتاحية",
        "insights_saved": "تم إنشاء وحفظ الملخص والكلمات المفتاحية.",
        "insights_title": "ملخص استخراجي",
        "insight_sources_title": "المقاطع التي بُني عليها الملخص",
        "topic_sources_title": "المقاطع المصدرية لهذا المحور",
        "keywords_title": "الكلمات المفتاحية",
        "topic_candidates_title": "محاور مستخلصة (مقترحة)",
        "topic_candidates_note": "تجميع إرشادي حسب تكرار الكلمات وظهورها معاً في المقاطع، وليس نموذجاً دلالياً لفهم الموضوعات.",
        "extractive_note": "هذا ملخص استخراجي مكوّن من جمل أصلية من التفريغ؛ لا يعيد صياغة الكلام أو يحوّل اللهجة إلى الفصحى.",
        "extract_keyframes": "استخراج الصور المصغّرة من الفيديو",
        "keyframes_done": "تم استخراج الصور المصغّرة.",
        "extracting_keyframes": "جاري استخراج الصور المصغّرة...",
        "keyframes_failed": "تعذر استخراج الصور المصغّرة",
        "keyframes_title": "الصور المصغّرة / اللقطات الرئيسية",
        "archive_notes_tab": "ملاحظات المراجعة",
        "archive_notes_title": "ملاحظات وتعليقات مرتبطة بالتوقيت",
        "archive_notes_desc": "أضف ملاحظة إلى ملف محدد عند توقيت معين، وراجع أو عدّل أو احذف الملاحظات. تُسجل عمليات التغيير في سجل الأحداث.",
        "archive_notes_media": "اختر ملف الوسائط",
        "archive_notes_timestamp": "التوقيت بالثواني",
        "archive_notes_author": "اسم صاحب الملاحظة",
        "archive_notes_text": "نص الملاحظة",
        "archive_notes_add": "إضافة الملاحظة",
        "archive_notes_empty": "لا توجد ملاحظات لهذا الملف بعد.",
        "archive_notes_saved": "تم حفظ الملاحظة.",
        "archive_notes_updated": "تم تحديث الملاحظة.",
        "archive_notes_deleted": "تم حذف الملاحظة.",
        "archive_notes_update": "حفظ التعديل",
        "archive_notes_updated_by": "تم التعديل بواسطة",
        "archive_notes_delete": "حذف الملاحظة",
        "archive_notes_play": "تشغيل المصدر من التوقيت",
        "archive_notes_created": "تاريخ الإضافة",
        "archive_qa_tab": "اسأل الأرشيف",
        "evaluation_tab": "تقييم البحث",
        "evaluation_title": "بناء مجموعة تقييم يدوية لنتائج البحث",
        "evaluation_desc": "ابحث عن مقاطع نصية أو لقطات فيديو ثم علّم النتائج ذات الصلة يدوياً. تُحفظ الأحكام في ملفات مستقلة لاستخدامها في حساب Precision وRecall وMRR.",
        "evaluation_query": "استعلام التقييم",
        "evaluation_mode": "طريقة الاسترجاع",
        "evaluation_cross_modal": "بحث موحّد (نص + لقطات)",
        "evaluation_frame_index": "رقم اللقطة",
        "evaluation_build_semantic": "بناء / تحديث الفهرس الدلالي لكل الأرشيف قبل البحث الدلالي أو الهجين",
        "evaluation_search": "اعرض المقاطع لتقييمها",
        "evaluation_relevant": "هذه النتيجة ذات صلة",
        "evaluation_play": "تشغيل المصدر عند هذا التوقيت",
        "evaluation_notes": "ملاحظات المراجع (اختياري)",
        "evaluation_save": "حفظ الأحكام اليدوية",
        "evaluation_saved": "تم حفظ الأحكام في data/evaluation/search_queries.json",
        "evaluation_cross_modal_saved": "تم حفظ أحكام النص واللقطات في data/evaluation/cross_modal_queries.json",
        "evaluation_select_relevant": "حدد نتيجة واحدة ذات صلة على الأقل قبل الحفظ.",
        "evaluation_dataset_count": "عدد الاستعلامات المحكّمة المحفوظة",
        "archive_qa_title": "اسأل الأرشيف واستعرض الأدلة",
        "archive_qa_desc": "اكتب سؤالاً للبحث في التفريغات النصية. الإجابة المعروضة اقتباس حرفي من أفضل مقطع، مع رابط إلى مصدره وتوقيته؛ لن يخمّن النظام عند غياب الأدلة.",
        "archive_qa_question": "ما الذي تريد معرفته من الأرشيف؟",
        "archive_qa_button": "اسأل الأرشيف",
        "archive_qa_semantic": "استخدم البحث الدلالي الاختياري",
        "archive_qa_answer": "إجابة مقتبسة حرفياً من التفريغ",
        "archive_qa_evidence": "الأدلة المسترجعة",
        "archive_qa_abstain": "لم نعثر على أدلة نصية كافية للإجابة ضمن النطاق المحدد.",
        "archive_qa_scope_note": "الاقتباس ليس إجابة مولّدة أو تلخيصاً؛ راجع السياق الأصلي قبل اعتماد الاستنتاج.",
        "archive_qa_retrieved_by": "مصدر الاسترجاع",
        "semantic": "بحث دلالي",
        "archive_qa_segment": "معرّف المقطع",
        "archive_qa_play": "تشغيل المصدر من هذا التوقيت",
        "archive_qa_semantic_unavailable": "تعذر تشغيل الاسترجاع الدلالي؛ سيستمر البحث النصي.",
        "archive_qa_matching_media": "عدد الملفات المطابقة للفلاتر",
        "archive_qa_filter_date_enabled": "تفعيل التصفية حسب تاريخ الإضافة",
        "archive_qa_collection": "المجموعة",
        "archive_qa_tags": "الوسوم",
        "archive_qa_local_llm": "إنشاء إجابة متعددة المقاطع باستخدام Ollama المحلي (اختياري)",
        "archive_qa_model": "اسم نموذج Ollama المحلي",
        "archive_qa_generated_note": "إجابة مولّدة محلياً؛ كل ادعاء مرتبط بمقطع مسترجع. تحقق من السياق لأن وجود الاستشهاد لا يثبت صحة الاستنتاج منطقياً.",
        "archive_qa_citations": "استشهادات الإجابة",
        "cross_modal_tab": "البحث الموحّد",
        "cross_modal_title": "بحث موحّد في النصوص واللقطات",
        "cross_modal_desc": "اجمع نتائج التفريغ النصي واللقطات البصرية في قائمة مرتبة واحدة. تُدمج الرتب ولا تُقارن درجات التشابه الخام بين النماذج.",
        "cross_modal_query": "اكتب وصفاً أو كلمة للبحث في النصوص والمشاهد",
        "cross_modal_button": "ابحث في النصوص واللقطات",
        "cross_modal_include_visual": "تضمين نتائج اللقطات البصرية",
        "cross_modal_image": "أو ابحث بصورة مرجعية (اللقطات المشابهة فقط)",
        "cross_modal_no_results": "لا توجد نتائج. تأكد من وجود تفريغات نصية وبناء فهرس اللقطات البصري.",
        "cross_modal_result_transcript": "نتيجة تفريغ نصي",
        "cross_modal_result_frame": "لقطة بصرية",
        "cross_modal_rank_score": "درجة دمج الرتب (RRF)",
        "cross_modal_visual_note": "يتطلب البحث البصري تثبيت المتطلبات الاختيارية وبناء فهرس اللقطات من تبويب البحث البصري.",
        "cross_modal_preview": "معاينة المصدر عند التوقيت",
        "visual_search_tab": "البحث البصري",
        "visual_play_at_time": "معاينة الفيديو عند هذا التوقيت",
        "visual_search_title": "البحث البصري داخل الفيديو",
        "visual_skipped": "تم تجاوز فيديوهات لأن ملف المصدر مفقود",
        "visual_search_hint": "ابحث بوصف نصي عربي أو بصورة مرجعية. يتطلب بناء فهرس اللقطات أولاً وتثبيت المتطلبات الاختيارية؛ يستخدم النموذج متعدد اللغات CLIP لمقارنة النصوص بالصور، وتُحفظ توقيتات الإطارات من FFmpeg.",
        "visual_time_note": "التوقيت مأخوذ من طوابع الإطارات التي يعيدها FFmpeg.",
        "visual_search_query": "صف المشهد الذي تبحث عنه",
        "visual_reference_image": "أو ارفع صورة مرجعية",
        "build_visual_index": "بناء / تحديث فهرس اللقطات البصري",
        "visual_index_done": "تم فهرسة اللقطات. عدد الصور",
        "visual_search_button": "ابحث بصرياً",
        "visual_search_empty": "اكتب وصفاً أو ارفع صورة مرجعية.",
        "visual_search_failed": "فشل البحث البصري",
        "visual_results": "نتائج البحث البصري",
        "visual_score": "درجة التشابه البصري",
        "no_visual_results": "لا توجد لقطات مطابقة. تأكد من بناء الفهرس للوسائط المطلوبة.",
        "keyframes_video_only": "استخراج اللقطات الرئيسية متاح لملفات الفيديو فقط.",
        "start": "البداية",
        "end": "النهاية",
        "save_changes": "حفظ تعديلات النص",
        "changes_saved": "تم حفظ تعديلات النص وإعادة فهرستها.",
        "save_failed_transcript": "تعذر حفظ تعديلات النص",
        "export_transcript": "تجهيز ملف التفريغ CSV",
        "download_transcript": "تنزيل التفريغ CSV",
        "export_failed": "تعذر تصدير الملف",
        "no_transcript": "لم يتم تفريغ هذا الفيديو بعد. ابدأ التفريغ من تبويب رفع الفيديو.",
        "search_title": "ابحث داخل محتوى الوسائط",
        "search_desc": "اكتب كلمة أو عبارة عربية للعثور على مواضع ظهورها في الفيديو أو التسجيل الصوتي.",
        "query": "كلمة أو عبارة البحث",
        "search_type": "نوع البحث",
        "exact": "بحث دقيق",
        "fuzzy": "بحث تقريبي",
        "hybrid": "بحث هجين ذكي",
        "build_semantic_index": "بناء/تحديث فهرس البحث الدلالي",
        "semantic_index_done": "تم تحديث فهرس البحث الدلالي. عدد المقاطع",
        "semantic_index_hint": "البحث الهجين يحتاج بناء الفهرس الدلالي أولاً. يتطلب تثبيت sentence-transformers وتنزيل النموذج عند أول استخدام.",
        "search_button": "بحث",
        "empty_query": "اكتب كلمة أو عبارة قبل بدء البحث.",
        "search_failed": "فشل البحث",
        "results": "نتائج البحث",
        "no_results": "لم يتم العثور على نتائج مطابقة.",
        "text": "النص",
        "time": "التوقيت",
        "similarity": "نسبة التشابه",
        "save_clip": "حفظ هذا المقطع",
        "clip_saved": "تم حفظ المقطع بنجاح.",
        "clip_failed": "تعذر حفظ المقطع",
        "clips_title": "المقاطع المحفوظة",
        "clips_desc": "شاهد المقاطع التي استخرجتها من الفيديو الحالي.",
        "no_clips": "لا توجد مقاطع محفوظة لهذا الفيديو حتى الآن.",
        "clip": "المقطع",
        "missing_clip": "ملف المقطع غير موجود",
        "export_clips": "تجهيز قائمة المقاطع CSV",
        "download_clips": "تنزيل قائمة المقاطع CSV",
        "load_clips_failed": "تعذر تحميل المقاطع المحفوظة",
        "footer": "نظام أرشفة وفهرسة الوسائط العربية والبحث في محتواها",
        "status_ready": "جاهز للعمل",
        "status_uploaded": "تم رفع الفيديو",
        "status_transcribed": "اكتمل التفريغ",
        "video_status": "حالة الملف",
        "duration_note": "تظهر نتائج البحث مع توقيتاتها لتسهيل الوصول إلى اللحظة المطلوبة.",
        "audio_clip_unavailable": "استخراج المقاطع متاح للفيديوهات فقط؛ يمكن البحث في هذا التسجيل الصوتي وعرض توقيتاته.",
        "search_scope": "نطاق البحث",
        "current_media": "الملف الحالي",
        "entire_archive": "كامل الأرشيف",
        "media_source": "المصدر",
        "media_preview": "معاينة المصدر",
        "no_archive_media": "لا توجد ملفات مفهرسة في الأرشيف حتى الآن.",
        "search_filters": "تصفية نتائج البحث",
        "filter_media_type": "نوع الوسائط",
        "filter_all": "الكل",
        "filter_video": "فيديو",
        "filter_audio": "صوت",
        "filter_source": "اسم المصدر يحتوي على",
        "filter_date": "تاريخ الإضافة",
        "filter_speaker": "المتحدث",
        "filter_no_speaker": "غير محدد",
    },
    "en": {
        "page_title": "Arabic Media Archiving & Search",
        "login": "Sign in",
        "logout": "Sign out",
        "username": "Username",
        "password": "Password",
        "current_password": "Current password",
        "new_password": "New password",
        "confirm_password": "Confirm password",
        "signed_in_as": "Signed in as",
        "change_password": "Change password",
        "auth_setup_error": "Could not initialize authentication: {error}",
        "auth_bootstrap_required": "Authentication is enabled but no administrator exists. Set ARCHIVE_ADMIN_USERNAME and ARCHIVE_ADMIN_PASSWORD (at least 12 characters), then restart the app.",
        "login_failed": "Incorrect username or password.",
        "login_rate_limited": "Too many sign-in attempts. Try again later.",
        "session_disabled": "This account has been disabled. Sign in with another account.",
        "session_changed": "This account's role or password changed. Please sign in again.",
        "password_changed": "Password changed successfully.",
        "password_mismatch": "The new passwords do not match.",
        "access_denied": "You do not have permission to access this section.",
        "auth_disabled": "User management requires ARCHIVE_AUTH_ENABLED=true.",
        "user_management_tab": "User Management",
        "user_management_title": "Archive User Accounts",
        "create_user": "Create user",
        "display_name": "Display name",
        "select_role": "Role",
        "role_administrator": "Administrator",
        "role_editor": "Editor",
        "role_search_only": "Search only",
        "users": "Users",
        "active": "Active",
        "update_user": "Update user",
        "reset_user_password": "Reset user password",
        "user_created": "User created.",
        "user_updated": "User updated.",
        "user_password_reset": "User password reset.",
        "subtitle": "Turn Arabic video and audio content into searchable text and find important moments with ease.",
        "language": "Language / اللغة",
        "arabic": "العربية",
        "english": "English",
        "project": "Graduation Project",
        "sidebar_title": "Main Menu",
        "sidebar_hint": "Upload a video or audio file to start transcription and search.",
        "upload_tab": "Add Media",
        "transcript_tab": "Transcript",
        "search_tab": "Video Search",
        "archive_qa_tab": "Ask the Archive",
        "evaluation_tab": "Search Evaluation",
        "evaluation_title": "Build a Human-Judged Search Evaluation Set",
        "evaluation_desc": "Search transcript segments or video keyframes and manually mark relevant results. Judgments are saved separately for Precision, Recall, and MRR evaluation.",
        "evaluation_query": "Evaluation query",
        "evaluation_mode": "Retrieval mode",
        "evaluation_cross_modal": "Unified cross-modal (text + frames)",
        "evaluation_frame_index": "Frame index",
        "evaluation_build_semantic": "Build / refresh the archive-wide semantic index before semantic or hybrid search",
        "evaluation_search": "Find segments to judge",
        "evaluation_relevant": "This result is relevant",
        "evaluation_play": "Play source at this timestamp",
        "evaluation_notes": "Reviewer notes (optional)",
        "evaluation_save": "Save human judgments",
        "evaluation_saved": "Judgments saved to data/evaluation/search_queries.json",
        "evaluation_cross_modal_saved": "Transcript and keyframe judgments saved to data/evaluation/cross_modal_queries.json",
        "evaluation_select_relevant": "Select at least one relevant result before saving.",
        "evaluation_dataset_count": "Saved judged queries",
        "archive_notes_tab": "Review Notes",
        "archive_notes_title": "Timestamped Notes and Comments",
        "archive_notes_desc": "Add a note to a media item at a specific timestamp, then review, edit, or delete notes. Changes are recorded in the audit history.",
        "archive_notes_media": "Select media",
        "archive_notes_timestamp": "Timestamp in seconds",
        "archive_notes_author": "Note author",
        "archive_notes_text": "Note text",
        "archive_notes_add": "Add note",
        "archive_notes_empty": "There are no notes for this media item yet.",
        "archive_notes_saved": "Note saved.",
        "archive_notes_updated": "Note updated.",
        "archive_notes_deleted": "Note deleted.",
        "archive_notes_update": "Save changes",
        "archive_notes_updated_by": "Updated by",
        "archive_notes_delete": "Delete note",
        "archive_notes_play": "Play source from timestamp",
        "archive_notes_created": "Created",
        "archive_qa_title": "Ask the Archive and Inspect Evidence",
        "archive_qa_desc": "Ask a question about indexed transcripts. The displayed answer is a verbatim quote from the best matching segment with its source and timestamp; the system abstains when evidence is missing.",
        "archive_qa_question": "What would you like to know from the archive?",
        "archive_qa_button": "Ask the Archive",
        "archive_qa_semantic": "Include optional semantic retrieval",
        "archive_qa_answer": "Verbatim transcript quote",
        "archive_qa_evidence": "Retrieved evidence",
        "archive_qa_abstain": "No sufficient transcript evidence was found in the selected scope.",
        "archive_qa_scope_note": "This quote is not a generated answer or summary; review the original context before drawing a conclusion.",
        "archive_qa_retrieved_by": "Retrieved by",
        "semantic": "Semantic",
        "archive_qa_segment": "Segment ID",
        "archive_qa_play": "Play source from this timestamp",
        "archive_qa_semantic_unavailable": "Semantic retrieval could not run; transcript search will continue.",
        "archive_qa_matching_media": "Media items matching filters",
        "archive_qa_filter_date_enabled": "Filter by added date",
        "archive_qa_collection": "Collection",
        "archive_qa_tags": "Tags",
        "archive_qa_local_llm": "Generate a multi-passage answer with local Ollama (optional)",
        "archive_qa_model": "Local Ollama model name",
        "archive_qa_generated_note": "Locally generated answer; each claim references a retrieved segment. Review the context because citation membership does not prove logical entailment.",
        "archive_qa_citations": "Answer citations",
        "clips_tab": "Saved Clips",
        "archive_tab": "Archive Management",
        "dashboard_tab": "Dashboard",
        "audit_tab": "Audit History",
        "audit_title": "Archive and Processing Audit History",
        "audit_actor": "Actor",
        "audit_entity": "Entity Type",
        "audit_all": "All",
        "audit_empty": "No audit events have been recorded yet.",
        "audit_details": "Event Details",
        "dashboard_title": "Archive and System Health",
        "dashboard_refresh": "Refresh Metrics",
        "dashboard_media": "Total Media",
        "dashboard_videos": "Videos",
        "dashboard_audio": "Audio Recordings",
        "dashboard_storage": "Stored Media Size",
        "dashboard_transcripts": "Transcript Files",
        "dashboard_missing": "Missing Source Files",
        "dashboard_status": "Processing Statuses",
        "dashboard_queue": "Queue Statuses",
        "dashboard_health": "System Health",
        "dashboard_db": "Database Check",
        "dashboard_ffmpeg": "FFmpeg",
        "dashboard_whisper": "Faster-Whisper",
        "dashboard_semantic": "Semantic Search",
        "dashboard_visual": "Visual Search",
        "dashboard_diarization": "Speaker Diarization",
        "available": "Available",
        "unavailable": "Unavailable",
        "dashboard_not_initialized": "Not initialized",
        "queue_tab": "Processing Queue",
        "queue_title": "Media Processing Jobs",
        "queue_desc": "Add a media folder to the durable queue, then run, retry, or cancel pending jobs.",
        "queue_input": "Media folder path on the application host",
        "queue_add": "Add Job to Queue",
        "queue_added": "Job added to the processing queue.",
        "queue_run_next": "Run Next Job",
        "queue_running": "Processing job...",
        "queue_completed": "Processing job completed.",
        "queue_failed": "Job failed",
        "queue_empty": "There are no queued jobs.",
        "queue_recover": "Recover jobs with an expired worker lease (15 minutes)",
        "queue_recovered": "Jobs recovered",
        "queue_cancel": "Cancel",
        "queue_cancel_requested": "Request cancellation",
        "queue_retry": "Retry",
        "queue_attempts": "Attempts",
        "queue_progress": "Progress",
        "queue_stage": "Processing stage",
        "queue_current_file": "Current file",
        "queue_stage_progress": "Stage progress",
        "queue_stage_starting": "Starting job",
        "queue_stage_scanning": "Scanning folder",
        "queue_stage_ready": "Folder scan complete",
        "queue_stage_verifying_source": "Verifying source file",
        "queue_stage_copying_source": "Copying into archive",
        "queue_stage_duplicate_skipped": "Skipping duplicate file",
        "queue_stage_checking_transcript": "Checking saved transcript",
        "queue_stage_loading_saved_transcript": "Loading saved transcript",
        "queue_stage_extracting_audio": "Extracting audio",
        "queue_stage_loading_model": "Loading transcription model",
        "queue_stage_transcribing": "Transcribing audio",
        "queue_stage_saving_transcript": "Saving transcript",
        "queue_stage_indexing_transcript": "Indexing transcript",
        "queue_stage_updating_catalog": "Updating archive catalog",
        "queue_stage_file_completed": "File completed",
        "queue_stage_file_failed": "File processing failed",
        "queue_stage_retry_wait": "Waiting for retry",
        "queue_stage_completed": "Job completed",
        "queue_stage_cancelled": "Job cancelled",
        "queue_stage_failed": "Job failed",
        "queue_stage_queued": "Queued",
        "queue_status": "Status",
        "queue_path_required": "Enter a valid folder path on the application host.",
        "queue_note": "Run a job manually here, or start an independent worker with python scripts/run_processing_worker.py so processing continues without an open browser. Active jobs can be asked to cancel safely after the current file finishes.",
        "archive_title": "Organize the Archive",
        "archive_desc": "Organize media into collections and add tags for easier archive management.",
        "archive_media": "Select an archive item",
        "collection": "Collection",
        "collection_placeholder": "e.g. News Interviews",
        "tags": "Tags",
        "tags_help": "Enter tags separated by commas.",
        "save_archive_metadata": "Save Organization Metadata",
        "archive_metadata_saved": "Collection and tags saved.",
        "filter_collection": "Filter by collection",
        "all_collections": "All collections",
        "filter_tags": "Filter by tags",
        "archive_items": "Archive Items",
        "no_archive_items": "No media items in the archive.",
        "upload_title": "Upload a Video or Audio File",
        "upload_help": "Video: MP4, MKV, MOV, AVI, WEBM | Audio: MP3, WAV, M4A, AAC, FLAC, OGG — Maximum size: 2 GB",
        "choose_video": "Choose a video or audio file",
        "unsupported": "Unsupported media format.",
        "too_large": "The file exceeds the maximum upload size of 2 GB.",
        "save_failed": "Failed to save video",
        "uploaded": "Media file added successfully.",
        "file": "File",
        "size": "Size",
        "video_preview": "Media Preview",
        "transcription_title": "Arabic Speech Transcription",
        "transcription_desc": "Prepare audio from a video or audio file and convert speech into timestamped Arabic text.",
        "start_transcription": "Start Transcription",
        "extracting_audio": "Extracting audio...",
        "loading_model": "Loading Whisper model and transcribing...",
        "transcription_done": "Transcription completed. Number of segments",
        "transcription_failed": "Transcription failed",
        "need_video": "Upload a video or audio file first to use these tools.",
        "transcript_title": "Review and Edit Transcript",
        "transcript_desc": "Review transcript segments, edit words when needed, and save changes to rebuild the search index.",
        "segment": "Segment",
        "play_segment": "Play from this timestamp",
        "selected_segment": "Preview from selected timestamp",
        "diarize_speakers": "Identify Speakers",
        "speaker_diarization_help": "Requires requirements-diarization.txt, HF_TOKEN, and access to the pyannote model. Segments without a confident temporal match are labeled UNKNOWN.",
        "diarization_unavailable": "The speaker model could not be initialized; segments were marked UNKNOWN so transcript review can continue.",
        "speaker": "Speaker",
        "generate_insights": "Generate Summary and Keywords",
        "insights_saved": "Summary and keywords generated and saved.",
        "insights_title": "Extractive Summary",
        "insight_sources_title": "Summary Source Segments",
        "topic_sources_title": "Source Segments for This Topic",
        "keywords_title": "Keywords",
        "topic_candidates_title": "Extracted Topic Candidates (Heuristic)",
        "topic_candidates_note": "Groups segments by keyword frequency and co-occurrence; this is not semantic topic modeling.",
        "extractive_note": "This summary selects original transcript sentences. It does not rewrite speech or convert dialect into Modern Standard Arabic.",
        "extract_keyframes": "Extract Video Keyframes",
        "keyframes_done": "Video keyframes extracted.",
        "extracting_keyframes": "Extracting video keyframes...",
        "keyframes_failed": "Keyframe extraction failed",
        "keyframes_title": "Thumbnails / Keyframes",
        "cross_modal_tab": "Unified Search",
        "cross_modal_title": "Unified Transcript & Visual Search",
        "cross_modal_desc": "Combine transcript and visual keyframe matches in one ranked list. Ranks are fused; raw similarity scores from different models are not compared.",
        "cross_modal_query": "Search words, phrases, or describe a scene",
        "cross_modal_button": "Search Text and Keyframes",
        "cross_modal_include_visual": "Include visual keyframe matches",
        "cross_modal_image": "Or search with a reference image (similar keyframes only)",
        "cross_modal_no_results": "No results. Check that transcripts exist and the visual keyframe index has been built.",
        "cross_modal_result_transcript": "Transcript match",
        "cross_modal_result_frame": "Visual keyframe",
        "cross_modal_rank_score": "Reciprocal Rank Fusion score",
        "cross_modal_visual_note": "Visual search requires optional dependencies and a keyframe index built from the Visual Search tab.",
        "cross_modal_preview": "Preview source at timestamp",
        "visual_search_tab": "Visual Search",
        "visual_play_at_time": "Preview video at this timestamp",
        "visual_search_title": "Visual Video Search",
        "visual_skipped": "Videos skipped (source file missing)",
        "visual_search_hint": "Search with an Arabic text description or a reference image. Build the keyframe index first and install the optional dependencies; multilingual CLIP compares text and images in a shared embedding space.",
        "visual_time_note": "Timestamps come from FFmpeg frame presentation timestamps.",
        "visual_search_query": "Describe the scene you are looking for",
        "visual_reference_image": "Or upload a reference image",
        "build_visual_index": "Build / Refresh Visual Keyframe Index",
        "visual_index_done": "Keyframes indexed. Image count",
        "visual_search_button": "Search Visually",
        "visual_search_empty": "Enter a description or upload a reference image.",
        "visual_search_failed": "Visual search failed",
        "visual_results": "Visual Search Results",
        "visual_score": "Visual similarity",
        "no_visual_results": "No matching keyframes found. Make sure the index is built for the selected media.",
        "keyframes_video_only": "Keyframe extraction is available for video files only.",
        "start": "Start",
        "end": "End",
        "save_changes": "Save Transcript Changes",
        "changes_saved": "Transcript changes saved and re-indexed.",
        "save_failed_transcript": "Failed to save transcript changes",
        "export_transcript": "Prepare Transcript CSV",
        "download_transcript": "Download Transcript CSV",
        "export_failed": "Failed to export file",
        "no_transcript": "This video has not been transcribed yet. Start transcription from the Video Upload tab.",
        "search_title": "Search Inside Media",
        "search_desc": "Enter an Arabic word or phrase to find where it appears in a video or audio recording.",
        "query": "Search word or phrase",
        "search_type": "Search type",
        "exact": "Exact Search",
        "fuzzy": "Fuzzy Search",
        "hybrid": "Hybrid Semantic Search",
        "build_semantic_index": "Build / Refresh Semantic Index",
        "semantic_index_done": "Semantic index updated. Number of segments",
        "semantic_index_hint": "Hybrid search requires building the semantic index first. Install sentence-transformers; the model downloads on first use.",
        "search_button": "Search",
        "empty_query": "Enter a word or phrase before searching.",
        "search_failed": "Search failed",
        "results": "Search Results",
        "no_results": "No matching results were found.",
        "text": "Text",
        "time": "Time",
        "similarity": "Similarity",
        "save_clip": "Save This Clip",
        "clip_saved": "Clip saved successfully.",
        "clip_failed": "Failed to save clip",
        "clips_title": "Saved Clips",
        "clips_desc": "Watch the clips extracted from the current video.",
        "no_clips": "No clips have been saved for this video yet.",
        "clip": "Clip",
        "missing_clip": "Clip file not found",
        "export_clips": "Prepare Clips CSV",
        "download_clips": "Download Clips CSV",
        "load_clips_failed": "Failed to load saved clips",
        "footer": "Arabic Media Archiving and Search System",
        "status_ready": "Ready",
        "status_uploaded": "Video uploaded",
        "status_transcribed": "Transcription complete",
        "video_status": "Media Status",
        "duration_note": "Search results include timestamps to help you locate the required moment.",
        "audio_clip_unavailable": "Clip extraction is available for video files only. You can still search this audio recording and view its timestamps.",
        "search_scope": "Search scope",
        "current_media": "Current file",
        "entire_archive": "Entire archive",
        "media_source": "Source",
        "media_preview": "Preview source",
        "no_archive_media": "There are no indexed media files in the archive yet.",
        "search_filters": "Search filters",
        "filter_media_type": "Media type",
        "filter_all": "All",
        "filter_video": "Video",
        "filter_audio": "Audio",
        "filter_source": "Source name contains",
        "filter_date": "Added date range",
        "filter_speaker": "Speaker",
        "filter_no_speaker": "Unspecified",
    },
}


# --------------------------------------------------
# Session state
# --------------------------------------------------

if "language" not in st.session_state:
    st.session_state.language = "ar"

if "video_path" not in st.session_state:
    st.session_state.video_path = None

if "media_path" not in st.session_state:
    st.session_state.media_path = None

if "media_type" not in st.session_state:
    st.session_state.media_type = None

if "video_id" not in st.session_state:
    st.session_state.video_id = None

if "segments" not in st.session_state:
    st.session_state.segments = []

if "transcribed" not in st.session_state:
    st.session_state.transcribed = False

if "search_results" not in st.session_state:
    st.session_state.search_results = []

if "transcript_export_path" not in st.session_state:
    st.session_state.transcript_export_path = None

if "clips_export_path" not in st.session_state:
    st.session_state.clips_export_path = None


# --------------------------------------------------
# Language and styling
# --------------------------------------------------

with st.sidebar:
    st.markdown("### 🌐 " + ("اللغة" if st.session_state.language == "ar" else "Language"))
    language_choice = st.radio(
        TEXT[st.session_state.language]["language"],
        options=["ar", "en"],
        format_func=lambda value: "العربية" if value == "ar" else "English",
        horizontal=True,
        label_visibility="collapsed",
        index=0 if st.session_state.language == "ar" else 1,
    )
    if language_choice != st.session_state.language:
        st.session_state.language = language_choice
        st.rerun()

lang = st.session_state.language
t = TEXT[lang]
is_ar = lang == "ar"
direction = "rtl" if is_ar else "ltr"
text_align = "right" if is_ar else "left"

auth_enabled = os.getenv("ARCHIVE_AUTH_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
auth_manager = None
if auth_enabled:
    try:
        auth_manager = get_auth_manager()
        if not auth_manager.has_users():
            bootstrap_username = os.getenv("ARCHIVE_ADMIN_USERNAME", "").strip()
            bootstrap_password = os.getenv("ARCHIVE_ADMIN_PASSWORD", "")
            if not bootstrap_username or not bootstrap_password:
                st.error(t["auth_bootstrap_required"])
                st.stop()
            auth_manager.bootstrap_admin(
                bootstrap_username,
                bootstrap_password,
                os.getenv("ARCHIVE_ADMIN_DISPLAY_NAME", "Archive Administrator"),
            )
    except Exception as error:
        st.error(t["auth_setup_error"].format(error=error))
        st.stop()

    session_username = st.session_state.get("archive_auth_username")
    session_version = st.session_state.get("archive_auth_session_version")
    current_user = (
        auth_manager.get_user(session_username)
        if session_username
        else None
    )
    session_invalidated = bool(
        current_user
        and session_version is not None
        and current_user["session_version"] != session_version
    )
    if current_user is None or not current_user["is_active"] or session_invalidated:
        if session_username:
            st.session_state.pop("archive_auth_username", None)
            st.session_state.pop("archive_auth_session_version", None)
            st.sidebar.warning(
                t["session_changed"] if session_invalidated else t["session_disabled"]
            )
        with st.sidebar.form("archive_login_form"):
            st.markdown("### " + t["login"])
            login_username = st.text_input(t["username"], key="archive_login_username")
            login_password = st.text_input(
                t["password"],
                type="password",
                key="archive_login_password",
            )
            login_submitted = st.form_submit_button(t["login"], use_container_width=True)
        if login_submitted:
            try:
                authenticated = auth_manager.authenticate(
                    login_username,
                    login_password,
                )
            except AuthRateLimitError:
                st.sidebar.error(t["login_rate_limited"])
            else:
                if authenticated:
                    st.session_state.archive_auth_username = authenticated["username"]
                    st.session_state.archive_auth_session_version = authenticated["session_version"]
                    st.session_state.pop("archive_login_password", None)
                    st.rerun()
                else:
                    st.sidebar.error(t["login_failed"])
        st.stop()

    current_user = auth_manager.get_user(session_username)
    with st.sidebar:
        st.caption(
            f'{t["signed_in_as"]}: {current_user["display_name"]} '
            f'({t["role_" + current_user["role"]]} )'
        )
        if st.button(t["logout"], key="archive_logout", use_container_width=True):
            st.session_state.pop("archive_auth_username", None)
            st.session_state.pop("archive_auth_session_version", None)
            st.session_state.pop("archive_login_password", None)
            st.rerun()
        with st.expander(t["change_password"]):
            with st.form("archive_change_password_form"):
                old_password = st.text_input(
                    t["current_password"],
                    type="password",
                    key="archive_current_password",
                )
                new_password = st.text_input(
                    t["new_password"],
                    type="password",
                    key="archive_new_password",
                )
                confirm_password = st.text_input(
                    t["confirm_password"],
                    type="password",
                    key="archive_confirm_password",
                )
                password_submitted = st.form_submit_button(t["change_password"])
            if password_submitted:
                if new_password != confirm_password:
                    st.error(t["password_mismatch"])
                else:
                    try:
                        updated_user = auth_manager.change_password(
                            current_user["username"],
                            old_password,
                            new_password,
                        )
                        st.session_state.archive_auth_session_version = updated_user["session_version"]
                        st.session_state.pop("archive_current_password", None)
                        st.session_state.pop("archive_new_password", None)
                        st.session_state.pop("archive_confirm_password", None)
                        st.success(t["password_changed"])
                    except (TypeError, ValueError, KeyError) as error:
                        st.error(str(error))
else:
    current_user = {
        "username": "local_user",
        "display_name": "Local User",
        "role": "administrator",
        "is_active": True,
    }

ROLE_PERMISSIONS = {
    "administrator": {
        "upload", "transcript", "search", "visual", "cross_modal",
        "qa", "evaluation", "notes", "clips", "archive", "queue", "dashboard",
        "audit", "users",
    },
    "editor": {
        "upload", "transcript", "search", "visual", "cross_modal",
        "qa", "evaluation", "notes", "clips", "archive", "queue", "dashboard", "audit",
    },
    "search_only": {"search", "visual", "cross_modal", "qa", "dashboard"},
}


def has_permission(permission: str) -> bool:
    if permission == "users" and not auth_enabled:
        return False
    return permission in ROLE_PERMISSIONS.get(current_user["role"], set())


st.markdown(
    f"""
    <style>
    .stApp {{
        background: linear-gradient(135deg, #0b1220 0%, #101a2d 55%, #0b1220 100%);
        color: #edf2f7;
    }}
    [data-testid="stHeader"] {{
        background: rgba(11, 18, 32, 0.85);
    }}
    [data-testid="stSidebar"] {{
        background: #101a2d;
        border-right: 1px solid rgba(148, 163, 184, 0.14);
    }}
    .block-container {{
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
        direction: {direction};
        text-align: {text_align};
    }}
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"],
    .stTextInput, .stTextArea, .stSelectbox, .stRadio {{
        direction: {direction};
        text-align: {text_align};
    }}
    h1, h2, h3, p, label {{
        text-align: {text_align};
    }}
    .hero {{
        position: relative;
        overflow: hidden;
        padding: 1.8rem 2rem;
        border: 1px solid rgba(96, 165, 250, 0.24);
        border-radius: 20px;
        background: linear-gradient(120deg, rgba(30, 64, 120, 0.42), rgba(15, 23, 42, 0.88));
        margin-bottom: 1.2rem;
        direction: {direction};
        text-align: {text_align};
        animation: hero-enter 420ms ease-out both;
    }}
    .hero::after {{
        content: "";
        position: absolute;
        width: 220px;
        height: 220px;
        border-radius: 50%;
        background: rgba(59, 130, 246, 0.08);
        filter: blur(34px);
        top: -125px;
        {"left" if is_ar else "right"}: -75px;
        pointer-events: none;
    }}
    @keyframes hero-enter {{
        from {{ opacity: 0; transform: translateY(7px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    .hero-kicker {{
        color: #93c5fd;
        font-size: 0.9rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        margin-bottom: 0.5rem;
    }}
    .hero h1 {{
        color: #f8fafc;
        font-size: clamp(1.8rem, 3vw, 2.6rem);
        margin: 0 0 0.65rem 0;
        line-height: 1.35;
    }}
    .hero p {{
        color: #cbd5e1;
        font-size: 1.05rem;
        margin: 0;
        line-height: 1.8;
    }}
    div[data-testid="stMetric"] {{
        background: rgba(30, 41, 59, 0.62);
        border: 1px solid rgba(148, 163, 184, 0.18);
        padding: 1rem;
        border-radius: 15px;
        transition: border-color 180ms ease, background-color 180ms ease;
    }}
    div[data-testid="stMetric"]:hover {{
        border-color: rgba(96, 165, 250, 0.38);
        background: rgba(36, 52, 76, 0.72);
    }}
    div[data-testid="stTabs"] button {{
        border-radius: 10px 10px 0 0;
        font-weight: 650;
        transition: color 160ms ease, background-color 160ms ease;
    }}
    div.stButton > button, div.stDownloadButton > button {{
        border-radius: 10px;
        min-height: 2.7rem;
        font-weight: 650;
        border: 1px solid rgba(96, 165, 250, 0.35);
        transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
    }}
    div.stButton > button:hover, div.stDownloadButton > button:hover {{
        border-color: rgba(96, 165, 250, 0.75);
        box-shadow: 0 5px 16px rgba(37, 99, 235, 0.13);
        transform: translateY(-1px);
    }}
    div.stButton > button:active, div.stDownloadButton > button:active {{
        transform: translateY(0);
    }}
    div.stButton > button:focus-visible, div.stDownloadButton > button:focus-visible {{
        outline: 2px solid #60a5fa;
        outline-offset: 2px;
    }}
    div.stButton > button[kind="primary"] {{
        background: linear-gradient(90deg, #2563eb, #0ea5e9);
        color: white;
        border: none;
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 15px;
        border-color: rgba(148, 163, 184, 0.2);
        background: rgba(15, 23, 42, 0.42);
        transition: border-color 180ms ease, background-color 180ms ease, transform 180ms ease;
    }}
    [data-testid="stVerticalBlockBorderWrapper"]:hover {{
        border-color: rgba(96, 165, 250, 0.34);
        background: rgba(20, 32, 53, 0.58);
    }}
    [data-testid="stProgressBar"] > div > div > div > div {{
        background: linear-gradient(90deg, #2563eb, #60a5fa);
    }}
    @media (prefers-reduced-motion: reduce) {{
        *, *::before, *::after {{
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
            scroll-behavior: auto !important;
        }}
    }}
    .small-muted {{
        color: #94a3b8;
        font-size: 0.9rem;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# Header
# --------------------------------------------------

st.markdown(
    f"""
    <div class="hero">
        <div class="hero-kicker">🎓 {t["project"]}</div>
        <h1>🎬 {t["page_title"]}</h1>
        <p>{t["subtitle"]}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.video_id:
    status = t["status_transcribed"] if st.session_state.transcribed else t["status_uploaded"]
    metric_label = t["video_status"]
else:
    status = t["status_ready"]
    metric_label = t["video_status"]

metric_col1, metric_col2, metric_col3 = st.columns(3)
with metric_col1:
    st.metric(metric_label, status)
with metric_col2:
    st.metric(t["transcript_tab"], len(st.session_state.segments))
with metric_col3:
    st.metric(t["results"], len(st.session_state.search_results))


# --------------------------------------------------
# Main sections
# --------------------------------------------------

tab_upload, tab_transcript, tab_search, tab_visual, tab_cross_modal, tab_qa, tab_evaluation, tab_notes, tab_clips, tab_archive, tab_queue, tab_dashboard, tab_audit, tab_users = st.tabs(
    [
        t["upload_tab"], t["transcript_tab"], t["search_tab"],
        t["visual_search_tab"], t["cross_modal_tab"], t["archive_qa_tab"],
        t["evaluation_tab"], t["archive_notes_tab"], t["clips_tab"],
        t["archive_tab"], t["queue_tab"], t["dashboard_tab"], t["audit_tab"],
        t["user_management_tab"],
    ]
)


# --------------------------------------------------
# 1. Media upload and transcription

with tab_upload:
    if not has_permission("upload"):
        st.info(t["access_denied"])
    else:
        st.subheader("📤 " + t["upload_title"])
        st.caption(t["upload_help"])

        uploaded_file = st.file_uploader(
            t["choose_video"],
            type=[extension.lstrip(".") for extension in sorted(ALLOWED_EXTENSIONS)],
            max_upload_size=MAX_UPLOAD_SIZE_MB,
            key="video_uploader",
        )

        if uploaded_file is not None:
            file_extension = Path(uploaded_file.name).suffix.lower()
            media_type = (
                "video" if file_extension in VIDEO_EXTENSIONS else "audio"
            )

            if file_extension not in ALLOWED_EXTENSIONS:
                st.error(t["unsupported"])
            elif uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
                st.error(t["too_large"])
            else:
                file_buffer = uploaded_file.getbuffer()
                try:
                    media_id = hashlib.sha256(file_buffer).hexdigest()
                    if media_type == "video":
                        media_path = (
                            Path("data/videos") / f"{media_id}{file_extension}"
                        )
                    else:
                        media_path = (
                            Path("data/audio/originals")
                            / f"{media_id}{file_extension}"
                        )

                    media_path.parent.mkdir(parents=True, exist_ok=True)

                    stored_file_is_valid = (
                        media_path.is_file()
                        and calculate_file_sha256(media_path) == media_id
                    )

                    if not stored_file_is_valid:
                        temporary_path = None
                        try:
                            file_descriptor, temporary_name = tempfile.mkstemp(
                                prefix=f".{media_id}.",
                                suffix=file_extension,
                                dir=media_path.parent,
                            )
                            temporary_path = Path(temporary_name)

                            with os.fdopen(file_descriptor, "wb") as output_file:
                                output_file.write(file_buffer)
                                output_file.flush()
                                os.fsync(output_file.fileno())

                            if calculate_file_sha256(temporary_path) != media_id:
                                raise RuntimeError(
                                    "Uploaded media changed while being saved."
                                )

                            os.replace(temporary_path, media_path)
                        finally:
                            if (
                                temporary_path is not None
                                and temporary_path.exists()
                            ):
                                temporary_path.unlink()
                except Exception as error:
                    st.error(f'{t["save_failed"]}: {error}')
                    st.stop()
                finally:
                    file_buffer.release()

                if (
                    st.session_state.video_id != media_id
                    or st.session_state.media_type != media_type
                ):
                    st.session_state.video_id = media_id
                    st.session_state.transcribed = False
                    st.session_state.segments = []
                    st.session_state.search_results = []
                    st.session_state.transcript_export_path = None
                    st.session_state.clips_export_path = None
                    st.session_state.transcript_insights = None

                    existing_transcript = Path(
                        f"data/transcripts/{media_id}.json"
                    )
                    if existing_transcript.exists():
                        try:
                            saved_segments = TranscriptManager.load(
                                str(existing_transcript)
                            )
                            indexer = TranscriptIndexer()
                            try:
                                indexer.index_segments(media_id, saved_segments)
                            finally:
                                indexer.close()

                            st.session_state.segments = saved_segments
                            st.session_state.transcribed = True
                        except Exception as error:
                            st.warning(
                                f'{t["no_transcript"]} {error}'
                            )

                st.session_state.media_path = str(media_path)
                st.session_state.media_type = media_type
                st.session_state.video_path = (
                    str(media_path) if media_type == "video" else None
                )
                try:
                    MediaCatalog().register_media(
                        media_id,
                        media_type,
                        uploaded_file.name,
                        str(media_path),
                        status=(
                            "transcribed"
                            if st.session_state.transcribed
                            else "uploaded"
                        ),
                    )
                except Exception as error:
                    st.error(f'{t["save_failed"]}: {error}')
                    st.stop()

                st.success(t["uploaded"])

                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    st.metric(t["file"], uploaded_file.name)
                with info_col2:
                    st.metric(
                        t["size"],
                        f"{uploaded_file.size / (1024 * 1024):.2f} MB",
                    )

                st.markdown("#### " + t["video_preview"])
                if media_type == "video":
                    st.video(str(media_path))
                else:
                    st.audio(str(media_path))

        st.divider()
        st.subheader("🎙️ " + t["transcription_title"])
        st.write(t["transcription_desc"])

        if not st.session_state.media_path:
            st.info(t["need_video"])
        elif st.button(
            t["start_transcription"],
            type="primary",
            use_container_width=True,
        ):
            media_id = st.session_state.video_id
            media_path = Path(st.session_state.media_path)
            audio_path = Path("data/audio") / f"{media_id}.wav"

            try:
                MediaCatalog().update_status(media_id, "processing")

                with st.spinner(t["extracting_audio"]):
                    AudioExtractor.prepare(str(media_path), str(audio_path))

                with st.spinner(t["loading_model"]):
                    engine = FasterWhisperEngine(model_size="tiny")
                    segments = engine.transcribe(str(audio_path))

                TranscriptManager.save(
                    segments,
                    f"data/transcripts/{media_id}.json",
                )
                insights_path = Path("data/insights") / f"{media_id}.json"
                if insights_path.is_file():
                    insights_path.unlink()
                st.session_state.transcript_insights = None

                indexer = TranscriptIndexer()
                try:
                    indexer.index_segments(media_id, segments)
                finally:
                    indexer.close()

                MediaCatalog().update_status(media_id, "transcribed")
                st.session_state.segments = segments
                st.session_state.transcribed = True
                st.session_state.search_results = []
                st.session_state.transcript_export_path = None
                st.success(f'{t["transcription_done"]}: {len(segments)}')
                st.rerun()

            except Exception as error:
                try:
                    MediaCatalog().update_status(media_id, "failed", str(error))
                except Exception:
                    pass
                st.error(f'{t["transcription_failed"]}: {error}')


    # 2. Transcript editor and export
# --------------------------------------------------

with tab_transcript:
    if not has_permission("transcript"):
        st.info(t["access_denied"])
    else:
        st.subheader("📝 " + t["transcript_title"])
        st.write(t["transcript_desc"])

        if not st.session_state.transcribed:
            st.info(t["no_transcript"])
        else:
            video_id = st.session_state.video_id
            edited_segments = []

            st.caption(t["speaker_diarization_help"])
            if st.button(t["diarize_speakers"]):
                try:
                    media_path = Path(st.session_state.media_path)
                    audio_path = Path("data/audio") / f"{video_id}.wav"
                    with st.spinner(t["loading_model"]):
                        if not audio_path.is_file():
                            AudioExtractor.prepare(str(media_path), str(audio_path))
                        try:
                            diarizer = PyannoteSpeakerDiarizer()
                        except RuntimeError:
                            annotated_segments = apply_speaker_turns(
                                st.session_state.segments, []
                            )
                            st.warning(t["diarization_unavailable"])
                        else:
                            annotated_segments = diarizer.annotate(
                                st.session_state.segments,
                                str(audio_path),
                            )
                        TranscriptManager.save(
                            annotated_segments,
                            f"data/transcripts/{video_id}.json",
                        )
                        indexer = TranscriptIndexer()
                        try:
                            indexer.index_segments(video_id, annotated_segments)
                        finally:
                            indexer.close()
                        st.session_state.segments = annotated_segments
                        st.session_state.search_results = []
                        st.success(t["diarize_speakers"])
                        st.rerun()
                except Exception as error:
                    st.error(f'{t["transcription_failed"]}: {error}')

            if st.button(t["generate_insights"]):
                try:
                    insights = TranscriptInsights.generate(st.session_state.segments)
                    TranscriptInsights.save(
                        insights,
                        Path("data/insights") / f"{video_id}.json",
                    )
                    st.session_state.transcript_insights = insights
                    st.success(t["insights_saved"])
                except Exception as error:
                    st.error(f'{t["transcription_failed"]}: {error}')

            insights_path = Path("data/insights") / f"{video_id}.json"
            if st.session_state.get("transcript_insights") is None and insights_path.is_file():
                try:
                    st.session_state.transcript_insights = TranscriptInsights.load(insights_path)
                except Exception:
                    st.session_state.transcript_insights = None

            current_insights = st.session_state.get("transcript_insights")
            if current_insights:
                st.markdown(f'#### {t["insights_title"]}')
                st.caption(t["extractive_note"])
                st.write(current_insights["summary"] or t["no_results"])
                if current_insights.get("source_segments"):
                    with st.expander(t["insight_sources_title"]):
                        for source in current_insights["source_segments"]:
                            st.caption(f'{source["start"]:.1f}s – {source["end"]:.1f}s')
                            st.write(source["text"])
                            if st.button(
                                t["play_segment"],
                                key=f'insight_source_{video_id}_{source["index"]}',
                            ):
                                st.session_state.transcript_seek = float(source["start"])
                if current_insights["keywords"]:
                    st.markdown(f'**{t["keywords_title"]}**')
                    st.write(", ".join(item["term"] for item in current_insights["keywords"]))
                if current_insights.get("topic_candidates"):
                    st.markdown(f'**{t["topic_candidates_title"]}**')
                    st.caption(t["topic_candidates_note"])
                    for topic_index, topic in enumerate(current_insights["topic_candidates"]):
                        with st.expander(
                            f'{topic["label"]} · {topic["segment_count"]} segments'
                        ):
                            st.write(", ".join(topic["keywords"]))
                            st.caption(t["topic_sources_title"])
                            for source in topic["source_segments"]:
                                st.caption(f'{source["start"]:.1f}s – {source["end"]:.1f}s')
                                st.write(source["text"])
                                if st.button(
                                    t["play_segment"],
                                    key=f'topic_source_{video_id}_{topic_index}_{source["index"]}',
                                ):
                                    st.session_state.transcript_seek = float(source["start"])

            if st.session_state.get("media_type") == "video":
                keyframe_dir = Path("data/keyframes") / video_id
                if st.button(t["extract_keyframes"]):
                    try:
                        with st.spinner(t["extracting_keyframes"]):
                            extracted_frames = KeyframeExtractor.extract(
                                st.session_state.media_path,
                                keyframe_dir,
                                return_timestamps=True,
                            )
                            keyframe_index = KeyframeSearchIndex()
                            try:
                                keyframe_index.replace_media_keyframes(
                                    video_id,
                                    extracted_frames,
                                    interval_seconds=30,
                                )
                            finally:
                                keyframe_index.close()
                        st.session_state.visual_search_results = None
                        st.success(t["keyframes_done"])
                    except Exception as error:
                        st.error(f'{t["keyframes_failed"]}: {error}')

                keyframe_paths = sorted(keyframe_dir.glob("keyframe_*.jpg"))
                if keyframe_paths:
                    keyframe_index = KeyframeSearchIndex()
                    try:
                        keyframe_metadata = keyframe_index.get_media_keyframes(video_id)
                    finally:
                        keyframe_index.close()
                    timestamp_by_path = {
                        item["image_path"]: item["timestamp_seconds"]
                        for item in keyframe_metadata
                    }
                    st.markdown(f'#### {t["keyframes_title"]}')
                    image_columns = st.columns(3)
                    for frame_index, frame_path in enumerate(keyframe_paths):
                        timestamp = timestamp_by_path.get(str(frame_path.resolve()))
                        caption = (
                            f"{timestamp:.1f}s" if timestamp is not None
                            else f"Frame {frame_index + 1}"
                        )
                        with image_columns[frame_index % len(image_columns)]:
                            st.image(
                                str(frame_path),
                                caption=caption,
                                use_container_width=True,
                            )

            for index, segment in enumerate(st.session_state.segments):
                with st.container(border=True):
                    time_col, text_col = st.columns([1.5, 5])
                    with time_col:
                        st.caption(f'{t["start"]}: {segment["start"]}s')
                        st.caption(f'{t["end"]}: {segment["end"]}s')
                        if segment.get("speaker"):
                            st.caption(f'{t["speaker"]}: {segment["speaker"]}')
                        if st.button(
                            t["play_segment"],
                            key=f"play_segment_{video_id}_{index}",
                        ):
                            st.session_state.transcript_seek = float(segment["start"])
                    with text_col:
                        edited_text = st.text_input(
                            f'{t["segment"]} {index + 1}',
                            value=segment["text"],
                            key=f"segment_{video_id}_{index}",
                        )

                    updated_segment = dict(segment)
                    updated_segment["text"] = edited_text
                    edited_segments.append(updated_segment)

            if st.session_state.get("transcript_seek") is not None:
                seek_time = max(0, int(st.session_state.transcript_seek))
                st.markdown(f'#### {t["selected_segment"]} · {seek_time}s')
                media_path = st.session_state.get("media_path")
                if media_path and Path(media_path).is_file():
                    if st.session_state.get("media_type") == "video":
                        st.video(media_path, start_time=seek_time)
                    else:
                        st.audio(media_path, start_time=seek_time)

            if st.button(t["save_changes"], type="primary"):
                try:
                    TranscriptManager.save(
                        edited_segments,
                        f"data/transcripts/{video_id}.json",
                    )
                    indexer = TranscriptIndexer()
                    try:
                        indexer.index_segments(video_id, edited_segments)
                    finally:
                        indexer.close()

                    st.session_state.segments = edited_segments
                    st.session_state.search_results = []
                    st.session_state.transcript_export_path = None
                    st.session_state.transcript_insights = None
                    insights_path = Path("data/insights") / f"{video_id}.json"
                    if insights_path.is_file():
                        insights_path.unlink()
                    st.success(t["changes_saved"])
                    st.rerun()
                except Exception as error:
                    st.error(f'{t["save_failed_transcript"]}: {error}')

            st.divider()
            if st.button(t["export_transcript"]):
                try:
                    export_path = TranscriptExporter.export_csv(
                        st.session_state.segments,
                        f"exports/{video_id}_transcript.csv",
                        video_id,
                    )
                    st.session_state.transcript_export_path = str(export_path)
                    st.rerun()
                except Exception as error:
                    st.error(f'{t["export_failed"]}: {error}')

            if st.session_state.transcript_export_path:
                export_path = Path(st.session_state.transcript_export_path)
                if export_path.exists():
                    st.download_button(
                        t["download_transcript"],
                        data=export_path.read_bytes(),
                        file_name=export_path.name,
                        mime="text/csv",
                        key=f"download_transcript_{video_id}",
                    )


# --------------------------------------------------
# 3. Search and clip creation

with tab_search:
    if not has_permission("search"):
        st.info(t["access_denied"])
    else:
        st.subheader("🔎 " + t["search_title"])
        st.write(t["search_desc"])

        search_scope = st.radio(
            t["search_scope"],
            [t["current_media"], t["entire_archive"]],
            horizontal=True,
            key=f"search_scope_{st.session_state.video_id or 'archive'}",
        )

        if st.session_state.get("search_results_scope") != search_scope:
            st.session_state.search_results = []
            st.session_state.visual_search_results = None
            st.session_state.search_results_scope = search_scope

        current_scope = search_scope == t["current_media"]
        if current_scope and not st.session_state.transcribed:
            st.info(t["no_transcript"])
        else:
            if not current_scope and not MediaCatalog().get_all():
                st.info(t["no_archive_media"])

            scope_key = (
                st.session_state.video_id if current_scope
                else "entire_archive"
            )
            query = st.text_input(
                t["query"],
                key=f"search_query_{scope_key}",
            )
            search_type = st.radio(
                t["search_type"],
                [t["exact"], t["fuzzy"], t["hybrid"]],
                horizontal=True,
                key=f"search_type_{scope_key}",
            )

            catalog = MediaCatalog()
            catalog_records = catalog.get_all()
            with st.expander(t["search_filters"], expanded=False):
                media_type_choice = st.selectbox(
                    t["filter_media_type"],
                    [t["filter_all"], t["filter_video"], t["filter_audio"]],
                    key=f"search_media_type_{scope_key}",
                )
                source_contains = st.text_input(
                    t["filter_source"],
                    key=f"search_source_{scope_key}",
                )
                collection_choice = st.selectbox(
                    t["filter_collection"],
                    [t["all_collections"]] + catalog.get_collections(),
                    key=f"search_collection_{scope_key}",
                )
                tag_choices = st.multiselect(
                    t["filter_tags"],
                    catalog.get_all_tags(),
                    key=f"search_tags_{scope_key}",
                )
                date_range = st.date_input(
                    t["filter_date"],
                    value=(),
                    key=f"search_date_range_{scope_key}",
                )
                filter_db = SearchEngine()
                try:
                    speaker_values = [
                        row["speaker"]
                        for row in filter_db.db.connection.execute(
                            "SELECT DISTINCT speaker FROM segments "
                            "WHERE speaker IS NOT NULL AND TRIM(speaker) != '' "
                            "ORDER BY speaker COLLATE NOCASE"
                        ).fetchall()
                    ]
                finally:
                    filter_db.close()
                speaker_choice = st.selectbox(
                    t["filter_speaker"],
                    [t["filter_all"], t["filter_no_speaker"]] + speaker_values,
                    key=f"search_speaker_{scope_key}",
                )

            selected_media_type = (
                None if media_type_choice == t["filter_all"]
                else "video" if media_type_choice == t["filter_video"]
                else "audio"
            )
            selected_start_date = (
                date_range[0].isoformat()
                if date_range and len(date_range) == 2 else None
            )
            selected_end_date = (
                date_range[1].isoformat()
                if date_range and len(date_range) == 2 else None
            )
            filtered_catalog = catalog.filter_media(
                collection=(
                    None if collection_choice == t["all_collections"]
                    else collection_choice
                ),
                tags=tag_choices,
                media_type=selected_media_type,
                source_contains=source_contains.strip() or None,
                start_date=selected_start_date,
                end_date=selected_end_date,
            )
            has_metadata_filters = (
                media_type_choice != t["filter_all"]
                or bool(source_contains.strip())
                or collection_choice != t["all_collections"]
                or bool(tag_choices)
                or (date_range and len(date_range) == 2)
            )
            allowed_media_ids = (
                [item["media_id"] for item in filtered_catalog]
                if has_metadata_filters else None
            )
            selected_speaker = (
                None if speaker_choice in (t["filter_all"], t["filter_no_speaker"])
                else speaker_choice
            )
            only_unspecified_speaker = speaker_choice == t["filter_no_speaker"]

            if search_type == t["hybrid"]:
                st.caption(t["semantic_index_hint"])

            if search_type == t["hybrid"] and st.button(t["build_semantic_index"]):
                search_engine = None
                try:
                    provider = SentenceTransformerProvider()
                    catalog_records = MediaCatalog().get_all()
                    search_engine = SearchEngine()
                    total_indexed = 0
                    progress = st.progress(0.0)
                    for position, record in enumerate(catalog_records, start=1):
                        total_indexed += search_engine.index_semantic_media(
                            record["media_id"], provider
                        )
                        progress.progress(position / max(len(catalog_records), 1))
                    st.success(f'{t["semantic_index_done"]}: {total_indexed}')
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')
                finally:
                    if search_engine is not None:
                        search_engine.close()

            if st.button(t["search_button"], type="primary"):
                if not query.strip():
                    st.warning(t["empty_query"])
                else:
                    search_engine = None
                    try:
                        search_engine = SearchEngine()
                        media_filter = (
                            st.session_state.video_id if current_scope else None
                        )
                        speaker_filter = (
                            "__UNSPECIFIED_SPEAKER__"
                            if only_unspecified_speaker else selected_speaker
                        )
                        search_options = {
                            "video_id": media_filter,
                            "media_ids": allowed_media_ids,
                            "speaker": speaker_filter,
                        }
                        if search_type == t["exact"]:
                            results = search_engine.exact_search(query, **search_options)
                        elif search_type == t["fuzzy"]:
                            results = search_engine.fuzzy_search(query, **search_options)
                        else:
                            provider = SentenceTransformerProvider()
                            results = search_engine.hybrid_search(
                                query, provider, **search_options
                            )

                        st.session_state.search_results = results
                        st.session_state.search_results_scope = search_scope
                    except Exception as error:
                        st.error(f'{t["search_failed"]}: {error}')
                    finally:
                        if search_engine is not None:
                            search_engine.close()

            st.caption(t["duration_note"])

            if st.session_state.search_results:
                st.markdown(
                    f"### {t['results']} ({len(st.session_state.search_results)})"
                )

                catalog_records = {
                    record["media_id"]: record
                    for record in MediaCatalog().get_all()
                }
                for result in st.session_state.search_results:
                    with st.container(border=True):
                        media_id = result["video_id"]
                        media_record = catalog_records.get(media_id)
                        media_path = None
                        media_type = None
                        source_name = media_id[:12]

                        if media_record:
                            media_path = Path(media_record["stored_path"])
                            media_type = media_record["media_type"]
                            source_name = media_record["source_name"]
                        elif (
                            media_id == st.session_state.video_id
                            and st.session_state.media_path
                        ):
                            media_path = Path(st.session_state.media_path)
                            media_type = st.session_state.media_type

                        st.caption(f'{t["media_source"]}: {source_name}')
                        if result.get("speaker"):
                            st.caption(f'{t["speaker"]}: {result["speaker"]}')
                        st.markdown(f'**{t["text"]}:** {result["original_text"]}')
                        st.markdown(
                            f'**{t["time"]}:** {result["start"]}s – {result["end"]}s'
                        )

                        if "similarity" in result:
                            st.progress(
                                max(0, min(100, int(result["similarity"]))) / 100,
                                text=f'{t["similarity"]}: {result["similarity"]}%',
                            )

                        if media_path and media_path.exists():
                            with st.expander(t["media_preview"]):
                                if media_type == "video":
                                    st.video(str(media_path))
                                else:
                                    st.audio(str(media_path))
                        else:
                            st.caption(t["missing_clip"])

                        if media_type == "video" and media_path and media_path.exists():
                            if st.button(
                                "✂️ " + t["save_clip"],
                                key=f"save_clip_{media_id}_{result['id']}",
                            ):
                                try:
                                    clip_path = ClipManager().create_clip(
                                        str(media_path),
                                        result["start"],
                                        result["end"],
                                        f"{media_id}_clip_{result['id']}",
                                    )
                                    ClipMetadata().save_clip(
                                        media_id,
                                        str(clip_path),
                                        result["start"],
                                        result["end"],
                                        result["original_text"],
                                    )
                                    st.success(t["clip_saved"])
                                except Exception as error:
                                    st.error(f'{t["clip_failed"]}: {error}')
                        elif media_type == "audio":
                            st.caption(t["audio_clip_unavailable"])
            else:
                st.info(t["no_results"])




# --------------------------------------------------
# 4. Visual keyframe search

with tab_visual:
    if not has_permission("visual"):
        st.info(t["access_denied"])
    else:
        st.subheader("🖼️ " + t["visual_search_title"])
        st.caption(t["visual_search_hint"])
        st.caption(t["visual_time_note"])
        visual_scope = st.radio(
            t["search_scope"],
            [t["current_media"], t["entire_archive"]],
            horizontal=True,
            key="visual_search_scope",
        )
        current_video_id = (
            st.session_state.get("video_id")
            if st.session_state.get("media_type") == "video"
            else None
        )
        if visual_scope == t["current_media"] and not current_video_id:
            st.info(t["keyframes_video_only"])
            visual_media_records = []
        else:
            visual_media_records = [
                record for record in MediaCatalog().get_all()
                if record["media_type"] == "video"
                and (
                    visual_scope == t["entire_archive"]
                    or record["media_id"] == current_video_id
                )
            ]
        visual_media_ids = [record["media_id"] for record in visual_media_records]
        visual_media_filter = (
            [current_video_id]
            if visual_scope == t["current_media"] and current_video_id
            else None
        )
        visual_context = (
            visual_scope,
            current_video_id if visual_scope == t["current_media"] else None,
        )
        if st.session_state.get("visual_search_context") != visual_context:
            st.session_state.visual_search_results = None
            st.session_state.visual_search_context = visual_context
        visual_query = st.text_input(
            t["visual_search_query"],
            key="visual_search_query_standalone",
        )
        reference_image = st.file_uploader(
            t["visual_reference_image"],
            type=["png", "jpg", "jpeg", "webp"],
            key="visual_reference_standalone",
        )

        if st.button(t["build_visual_index"], key="build_visual_index_standalone"):
            visual_index = None
            try:
                visual_provider = SentenceTransformerVisualProvider()
                visual_index = KeyframeSearchIndex()
                total_indexed = 0
                skipped = 0
                progress = st.progress(0.0)
                for position, record in enumerate(visual_media_records, start=1):
                    frame_dir = Path("data/keyframes") / record["media_id"]
                    frames = sorted(frame_dir.glob("keyframe_*.jpg"))
                    source_path = Path(record["stored_path"])
                    if not frames:
                        if not source_path.is_file():
                            skipped += 1
                            progress.progress(position / max(len(visual_media_records), 1))
                            continue
                        timestamped_frames = KeyframeExtractor.extract(
                            source_path,
                            frame_dir,
                            return_timestamps=True,
                        )
                        visual_index.replace_media_keyframes(
                            record["media_id"], timestamped_frames
                        )
                    else:
                        existing_frames = visual_index.get_media_keyframes(
                            record["media_id"]
                        )
                        existing_paths = [
                            item["image_path"] for item in existing_frames
                        ]
                        current_paths = [str(path.resolve()) for path in frames]
                        if existing_paths == current_paths:
                            timestamped_metadata = [
                                (Path(item["image_path"]), item["timestamp_seconds"])
                                for item in existing_frames
                            ]
                            # Re-hash the image files so externally changed frames
                            # invalidate their stale visual embeddings.
                            visual_index.replace_media_keyframes(
                                record["media_id"], timestamped_metadata
                            )
                        else:
                            if not source_path.is_file():
                                raise FileNotFoundError(
                                    f'Original video is missing: {source_path}'
                                )
                            timestamped_frames = KeyframeExtractor.extract(
                                source_path,
                                frame_dir,
                                return_timestamps=True,
                            )
                            visual_index.replace_media_keyframes(
                                record["media_id"], timestamped_frames
                            )
                    total_indexed += visual_index.index_media(
                        record["media_id"], visual_provider
                    )
                    progress.progress(position / max(len(visual_media_records), 1))
                st.session_state.visual_search_results = None
                st.success(
                    f'{t["visual_index_done"]}: {total_indexed} · '
                    f'{t["visual_skipped"]}: {skipped}'
                )
            except Exception as error:
                st.error(f'{t["visual_search_failed"]}: {error}')
            finally:
                if visual_index is not None:
                    visual_index.close()

        if st.button(t["visual_search_button"], key="run_visual_search_standalone"):
            if not visual_query.strip() and reference_image is None:
                st.warning(t["visual_search_empty"])
            elif not visual_media_ids:
                st.warning(t["no_visual_results"])
            else:
                visual_index = None
                temporary_reference = None
                try:
                    visual_provider = SentenceTransformerVisualProvider()
                    visual_index = KeyframeSearchIndex()
                    if reference_image is not None:
                        suffix = Path(reference_image.name).suffix or ".jpg"
                        with tempfile.NamedTemporaryFile(
                            suffix=suffix, delete=False
                        ) as temp_file:
                            temp_file.write(reference_image.getvalue())
                            temporary_reference = Path(temp_file.name)
                        visual_results = visual_index.search_image(
                            temporary_reference,
                            visual_provider,
                            media_ids=visual_media_filter,
                        )
                    else:
                        visual_results = visual_index.search_text(
                            visual_query,
                            visual_provider,
                            media_ids=visual_media_filter,
                        )
                    st.session_state.visual_search_results = visual_results
                except Exception as error:
                    st.error(f'{t["visual_search_failed"]}: {error}')
                finally:
                    if temporary_reference and temporary_reference.exists():
                        temporary_reference.unlink()
                    if visual_index is not None:
                        visual_index.close()

        visual_results = st.session_state.get("visual_search_results")
        if visual_results:
            st.markdown(f'#### {t["visual_results"]} ({len(visual_results)})')
            visual_catalog = {
                item["media_id"]: item for item in MediaCatalog().get_all()
            }
            for visual_result in visual_results:
                with st.container(border=True):
                    image_path = Path(visual_result["image_path"])
                    if image_path.is_file():
                        st.image(
                            str(image_path),
                            caption=(
                                f'{visual_catalog.get(visual_result["media_id"], {}).get("source_name", visual_result["media_id"][:12])} · '
                                f'{visual_result["timestamp_seconds"]:.2f}s'
                            ),
                            use_container_width=True,
                        )
                    st.caption(
                        f'{t["visual_score"]}: {visual_result["visual_score"]:.3f}'
                    )
                    source_record = visual_catalog.get(visual_result["media_id"])
                    if source_record:
                        st.caption(f'{t["media_source"]}: {source_record["source_name"]}')
                    st.caption(
                        f'{t["time"]}: {visual_result["timestamp_seconds"]:.2f}s'
                    )
                    source_path = (
                        Path(source_record["stored_path"])
                        if source_record else None
                    )
                    if source_path and source_path.is_file() and st.button(
                        t["visual_play_at_time"],
                        key=f'visual_play_{visual_result["keyframe_id"]}',
                    ):
                        st.video(
                            str(source_path),
                            start_time=int(visual_result["timestamp_seconds"]),
                        )
        elif visual_results == []:
            st.info(t["no_visual_results"])


    # 5. Unified transcript + visual search
# --------------------------------------------------

with tab_cross_modal:
    if not has_permission("cross_modal"):
        st.info(t["access_denied"])
    else:
        st.subheader("🔎 " + t["cross_modal_title"])
        st.caption(t["cross_modal_desc"])
        cross_scope = st.radio(
            t["search_scope"],
            [t["current_media"], t["entire_archive"]],
            horizontal=True,
            key="cross_modal_scope",
        )
        current_media_id = st.session_state.get("video_id")
        cross_records = MediaCatalog().get_all()
        if cross_scope == t["current_media"]:
            if not current_media_id:
                st.info(t["no_archive_media"])
                cross_media_ids = []
            else:
                cross_media_ids = [current_media_id]
        else:
            cross_media_ids = [item["media_id"] for item in cross_records]

        cross_context = (cross_scope, tuple(cross_media_ids))
        if st.session_state.get("cross_modal_context") != cross_context:
            st.session_state.cross_modal_results = None
            st.session_state.cross_modal_context = cross_context

        cross_query = st.text_input(
            t["cross_modal_query"], key="cross_modal_query_input"
        )
        include_visual = st.checkbox(
            t["cross_modal_include_visual"],
            value=True,
            key="cross_modal_include_visual_toggle",
            help=t["cross_modal_visual_note"],
        )
        cross_reference = st.file_uploader(
            t["cross_modal_image"],
            type=["png", "jpg", "jpeg", "webp"],
            key="cross_modal_reference_image",
        )
        if st.button(t["cross_modal_button"], type="primary", key="run_cross_modal_search"):
            st.session_state.cross_modal_results = None
            if not cross_query.strip() and cross_reference is None:
                st.warning(t["empty_query"])
            elif not cross_media_ids:
                st.info(t["cross_modal_no_results"])
            else:
                cross_engine = None
                cross_index = None
                temporary_reference = None
                try:
                    cross_engine = SearchEngine()
                    cross_index = KeyframeSearchIndex()
                    cross_search = CrossModalSearch(cross_engine, cross_index)
                    if cross_reference is not None:
                        cross_provider = SentenceTransformerVisualProvider()
                        suffix = Path(cross_reference.name).suffix or ".jpg"
                        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                            temp_file.write(cross_reference.getvalue())
                            temporary_reference = Path(temp_file.name)
                        cross_results = cross_search.search_image(
                            temporary_reference,
                            cross_provider,
                            media_ids=cross_media_ids,
                        )
                    else:
                        cross_provider = None
                        if include_visual:
                            try:
                                cross_provider = SentenceTransformerVisualProvider()
                            except Exception as provider_error:
                                st.warning(
                                    f'{t["cross_modal_visual_note"]} ({provider_error})'
                                )
                        cross_results = cross_search.search_text(
                            cross_query,
                            media_ids=cross_media_ids,
                            visual_provider=cross_provider,
                            include_visual=include_visual and cross_provider is not None,
                        )
                    st.session_state.cross_modal_results = cross_results
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')
                finally:
                    if temporary_reference and temporary_reference.exists():
                        temporary_reference.unlink()
                    if cross_index is not None:
                        cross_index.close()
                    if cross_engine is not None:
                        cross_engine.close()

        cross_results = st.session_state.get("cross_modal_results")
        cross_catalog = {item["media_id"]: item for item in cross_records}
        if cross_results:
            st.markdown(f'### {t["results"]} ({len(cross_results)})')
            for result_index, result in enumerate(cross_results):
                media_id = result["media_id"]
                source_record = cross_catalog.get(media_id)
                source_name = (
                    source_record["source_name"] if source_record
                    else media_id[:12]
                )
                source_path = (
                    Path(source_record["stored_path"]) if source_record else None
                )
                with st.container(border=True):
                    result_label = (
                        t["cross_modal_result_frame"]
                        if result["result_type"] == "keyframe"
                        else t["cross_modal_result_transcript"]
                    )
                    st.markdown(f'**{result_index + 1}. {result_label}**')
                    st.caption(f'{t["media_source"]}: {source_name}')
                    st.caption(
                        f'{t["time"]}: {result["timestamp_seconds"]:.2f}s · '
                        f'{t["cross_modal_rank_score"]}: {result["cross_modal_score"]:.4f}'
                    )
                    matched_labels = {
                        "exact": t["exact"],
                        "fuzzy": t["fuzzy"],
                        "visual": t["visual_search_tab"],
                    }
                    st.caption(" + ".join(
                        matched_labels.get(source, source)
                        for source in result["matched_by"]
                    ))
                    if result["result_type"] == "keyframe":
                        frame_path = Path(result["image_path"])
                        if frame_path.is_file():
                            st.image(str(frame_path), use_container_width=True)
                        if "visual_score" in result:
                            st.caption(
                                f'{t["visual_score"]}: {result["visual_score"]:.3f}'
                            )
                        if source_path and source_path.is_file() and st.button(
                            t["cross_modal_preview"],
                            key=f'cross_modal_preview_{result["keyframe_id"]}_{result_index}',
                        ):
                            st.video(
                                str(source_path),
                                start_time=int(result["timestamp_seconds"]),
                            )
                    else:
                        st.markdown(f'**{t["text"]}:** {result["original_text"]}')
                        st.caption(
                            f'{t["start"]}: {result["start"]}s · '
                            f'{t["end"]}: {result["end"]}s'
                        )
                        if result.get("speaker"):
                            st.caption(f'{t["speaker"]}: {result["speaker"]}')
                        if source_path and source_path.is_file() and st.button(
                            t["cross_modal_preview"],
                            key=f'cross_modal_preview_{result["id"]}_{result_index}',
                        ):
                            if source_record and source_record["media_type"] == "video":
                                st.video(str(source_path), start_time=int(result["start"]))
                            else:
                                st.audio(str(source_path), start_time=int(result["start"]))
        elif cross_results == []:
            st.info(t["cross_modal_no_results"])


    # 6. Evidence-first archive Q&A
# --------------------------------------------------

with tab_qa:
    if not has_permission("qa"):
        st.info(t["access_denied"])
    else:
        st.subheader("💬 " + t["archive_qa_title"])
        st.caption(t["archive_qa_desc"])

        qa_scope = st.radio(
            t["search_scope"],
            [t["current_media"], t["entire_archive"]],
            horizontal=True,
            key="archive_qa_scope",
        )
        qa_catalog_manager = MediaCatalog()
        qa_records = qa_catalog_manager.get_all()
        with st.expander(t["search_filters"], expanded=False):
            qa_media_type_label = st.selectbox(
                t["filter_media_type"],
                [t["filter_all"], t["filter_video"], t["filter_audio"]],
                key="archive_qa_media_type",
            )
            qa_source_filter = st.text_input(
                t["filter_source"],
                key="archive_qa_source_filter",
            )
            qa_filter_date_enabled = st.checkbox(
                t["archive_qa_filter_date_enabled"],
                value=False,
                key="archive_qa_filter_date_enabled",
            )
            qa_date_range = (
                st.date_input(
                    t["filter_date"],
                    value=(date.today() - timedelta(days=30), date.today()),
                    key="archive_qa_date_range",
                )
                if qa_filter_date_enabled else ()
            )
            qa_collections = qa_catalog_manager.get_collections()
            qa_collection_label = st.selectbox(
                t["archive_qa_collection"],
                [t["filter_all"], *qa_collections],
                key="archive_qa_collection_filter",
            )
            qa_available_tags = qa_catalog_manager.get_all_tags()
            qa_selected_tags = st.multiselect(
                t["archive_qa_tags"],
                qa_available_tags,
                key="archive_qa_tag_filter",
            )

        qa_type_value = {
            t["filter_all"]: None,
            t["filter_video"]: "video",
            t["filter_audio"]: "audio",
        }[qa_media_type_label]
        qa_date_values = (
            qa_date_range
            if isinstance(qa_date_range, (tuple, list)) else ()
        )
        qa_start_date = (
            qa_date_values[0].isoformat() if len(qa_date_values) >= 1 else None
        )
        qa_end_date = (
            qa_date_values[1].isoformat() if len(qa_date_values) >= 2 else None
        )
        try:
            qa_filtered_records = qa_catalog_manager.filter_media(
                media_type=qa_type_value,
                source_contains=qa_source_filter.strip() or None,
                start_date=qa_start_date,
                end_date=qa_end_date,
                collection=(
                    qa_collection_label
                    if qa_collection_label != t["filter_all"] else None
                ),
                tags=qa_selected_tags,
            )
        except (TypeError, ValueError) as filter_error:
            st.warning(f'{t["search_failed"]}: {filter_error}')
            qa_filtered_records = []
        qa_current_media_id = st.session_state.get("video_id")
        if qa_scope == t["current_media"]:
            qa_media_ids = [
                item["media_id"] for item in qa_filtered_records
                if item["media_id"] == qa_current_media_id
            ]
        else:
            qa_media_ids = [item["media_id"] for item in qa_filtered_records]
        st.caption(
            f'{t["archive_qa_matching_media"]}: {len(qa_media_ids)}'
        )
        qa_speaker_engine = SearchEngine()
        try:
            qa_speaker_names = qa_speaker_engine.list_speakers(
                media_ids=qa_media_ids
            )
        finally:
            qa_speaker_engine.close()
        qa_speaker_label = st.selectbox(
            t["filter_speaker"],
            [t["filter_all"], t["filter_no_speaker"], *qa_speaker_names],
            key="archive_qa_speaker_filter",
        )
        qa_speaker_filter = (
            None if qa_speaker_label == t["filter_all"]
            else UNSPECIFIED_SPEAKER
            if qa_speaker_label == t["filter_no_speaker"]
            else qa_speaker_label
        )

        qa_question = st.text_area(
            t["archive_qa_question"],
            key="archive_qa_question_input",
            height=100,
        )
        qa_use_semantic = st.checkbox(
            t["archive_qa_semantic"],
            value=False,
            key="archive_qa_use_semantic",
        )
        qa_use_local_llm = st.checkbox(
            t["archive_qa_local_llm"],
            value=False,
            key="archive_qa_use_local_llm",
        )
        qa_local_model = (
            st.text_input(
                t["archive_qa_model"],
                value="qwen2.5:3b",
                key="archive_qa_local_model",
            )
            if qa_use_local_llm else "qwen2.5:3b"
        )
        qa_context = (
            qa_scope, tuple(qa_media_ids), qa_speaker_filter,
            qa_question.strip(), qa_use_semantic, qa_use_local_llm,
            qa_local_model.strip()
        )
        if st.session_state.get("archive_qa_context") != qa_context:
            st.session_state.archive_qa_result = None
            st.session_state.archive_qa_context = qa_context

        if st.button(
            t["archive_qa_button"],
            type="primary",
            key="run_archive_qa",
        ):
            if not qa_question.strip():
                st.warning(t["empty_query"])
            else:
                qa_engine = None
                try:
                    qa_engine = SearchEngine()
                    qa_semantic_provider = None
                    if qa_use_semantic:
                        try:
                            qa_semantic_provider = SentenceTransformerProvider()
                        except Exception as provider_error:
                            st.warning(
                                f'{t["archive_qa_semantic_unavailable"]} ({provider_error})'
                            )
                    qa_answer_provider = None
                    if qa_use_local_llm:
                        try:
                            qa_answer_provider = OllamaAnswerProvider(
                                model=qa_local_model.strip()
                            )
                        except Exception as provider_error:
                            st.warning(str(provider_error))
                    qa_result = ArchiveQA(qa_engine).ask(
                        qa_question,
                        media_ids=qa_media_ids,
                        speaker=qa_speaker_filter,
                        semantic_provider=qa_semantic_provider,
                        answer_provider=qa_answer_provider,
                    )
                    st.session_state.archive_qa_result = qa_result
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')
                finally:
                    if qa_engine is not None:
                        qa_engine.close()

        qa_result = st.session_state.get("archive_qa_result")
        if qa_result:
            for warning in qa_result.get("warnings", []):
                st.warning(warning)

            if qa_result["status"] == "evidence_found":
                st.markdown(f'### {t["archive_qa_answer"]}')
                if qa_result["answer_type"] == "cited_generated_claims":
                    st.caption(t["archive_qa_generated_note"])
                st.success(qa_result["answer"])
                st.caption(t["archive_qa_scope_note"])
                answer_citations = qa_result.get("answer_citations", [])
                if answer_citations:
                    st.caption(
                        f'{t["archive_qa_citations"]}: '
                        + ", ".join(
                            f'{item["media_id"]} · #{item["segment_id"]} '
                            f'({item["start"]:.2f}s–{item["end"]:.2f}s)'
                            for item in answer_citations
                        )
                    )

                qa_catalog = {item["media_id"]: item for item in qa_records}
                st.markdown(f'#### {t["archive_qa_evidence"]}')
                for evidence in qa_result["evidence"]:
                    media_id = evidence["media_id"]
                    source_record = qa_catalog.get(media_id)
                    source_name = (
                        source_record["source_name"]
                        if source_record else media_id[:12]
                    )
                    source_path = (
                        Path(source_record["stored_path"])
                        if source_record else None
                    )
                    with st.container(border=True):
                        st.markdown(
                            f'**{evidence["rank"]}. {source_name}**'
                        )
                        st.caption(
                            f'{t["archive_qa_segment"]}: {evidence["segment_id"]} · '
                            f'{t["start"]}: {evidence["start"]:.2f}s · '
                            f'{t["end"]}: {evidence["end"]:.2f}s'
                        )
                        if evidence.get("speaker"):
                            st.caption(f'{t["speaker"]}: {evidence["speaker"]}')
                        source_labels = {
                            "exact": t["exact"],
                            "fuzzy": t["fuzzy"],
                            "semantic": t["semantic"],
                        }
                        st.caption(
                            f'{t["archive_qa_retrieved_by"]}: '
                            + ", ".join(
                                source_labels.get(source, source)
                                for source in evidence["retrieved_by"]
                            )
                        )
                        st.write(evidence["text"])
                        if source_path and source_path.is_file() and st.button(
                            t["archive_qa_play"],
                            key=f'archive_qa_play_{media_id}_{evidence["segment_id"]}',
                        ):
                            if source_record["media_type"] == "video":
                                st.video(
                                    str(source_path),
                                    start_time=int(evidence["start"]),
                                )
                            else:
                                st.audio(
                                    str(source_path),
                                    start_time=int(evidence["start"]),
                                )
            else:
                st.info(t["archive_qa_abstain"])


    # 7. Human-judged search evaluation
# --------------------------------------------------

with tab_evaluation:
    if not has_permission("evaluation"):
        st.info(t["access_denied"])
    else:
        st.subheader("📊 " + t["evaluation_title"])
        st.caption(t["evaluation_desc"])
        evaluation_store = EvaluationDatasetStore()
        cross_modal_evaluation_store = CrossModalEvaluationDatasetStore()

        evaluation_query = st.text_input(
            t["evaluation_query"],
            key="evaluation_query_input",
        )
        evaluation_mode_label = st.selectbox(
            t["evaluation_mode"],
            [t["exact"], t["fuzzy"], t["semantic"], t["hybrid"], t["evaluation_cross_modal"]],
            key="evaluation_mode",
        )
        evaluation_is_cross_modal = (
            evaluation_mode_label == t["evaluation_cross_modal"]
        )
        evaluation_build_semantic = (
            st.checkbox(
                t["evaluation_build_semantic"],
                value=False,
                key="evaluation_build_semantic",
            )
            if evaluation_mode_label in (t["semantic"], t["hybrid"]) else False
        )
        if evaluation_is_cross_modal:
            st.info(t["cross_modal_visual_note"])

        selected_evaluation_store = (
            cross_modal_evaluation_store
            if evaluation_is_cross_modal else evaluation_store
        )
        try:
            evaluation_dataset = selected_evaluation_store.load()
            st.metric(
                t["evaluation_dataset_count"],
                len(evaluation_dataset["queries"]),
            )
        except Exception as error:
            evaluation_dataset = {"queries": []}
            st.error(f'{t["search_failed"]}: {error}')

        evaluation_context = (
            evaluation_query.strip(),
            evaluation_mode_label,
            evaluation_build_semantic,
        )
        if st.session_state.get("evaluation_context") != evaluation_context:
            st.session_state.evaluation_results = None
            st.session_state.evaluation_context = evaluation_context

        if st.button(
            t["evaluation_search"],
            type="primary",
            key="evaluation_search_button",
        ):
            if not evaluation_query.strip():
                st.warning(t["empty_query"])
            else:
                evaluation_engine = None
                evaluation_visual_index = None
                try:
                    evaluation_engine = SearchEngine()
                    if evaluation_is_cross_modal:
                        evaluation_visual_provider = SentenceTransformerVisualProvider()
                        evaluation_visual_index = KeyframeSearchIndex()
                        evaluation_cross_modal = CrossModalSearch(
                            evaluation_engine,
                            evaluation_visual_index,
                        )
                        found_results = evaluation_cross_modal.search_text(
                            evaluation_query,
                            limit=10,
                            visual_provider=evaluation_visual_provider,
                            include_visual=True,
                        )
                    elif evaluation_mode_label in (t["semantic"], t["hybrid"]):
                        evaluation_provider = SentenceTransformerProvider()
                        if evaluation_build_semantic:
                            media_ids = [
                                row["video_id"]
                                for row in evaluation_engine.db.connection.execute(
                                    "SELECT DISTINCT video_id FROM segments ORDER BY video_id"
                                ).fetchall()
                            ]
                            with st.spinner(t["build_semantic_index"]):
                                for media_id in media_ids:
                                    evaluation_engine.index_semantic_media(
                                        media_id, evaluation_provider
                                    )
                        if evaluation_mode_label == t["semantic"]:
                            found_results = evaluation_engine.semantic_search(
                                evaluation_query,
                                evaluation_provider,
                                limit=10,
                            )
                        else:
                            found_results = evaluation_engine.hybrid_search(
                                evaluation_query,
                                evaluation_provider,
                                limit=10,
                            )
                    elif evaluation_mode_label == t["fuzzy"]:
                        found_results = evaluation_engine.fuzzy_search(
                            evaluation_query, limit=10
                        )
                    else:
                        found_results = evaluation_engine.exact_search(
                            evaluation_query, limit=10
                        )
                    st.session_state.evaluation_results = found_results
                    st.session_state.evaluation_result_query = evaluation_query.strip()
                    st.session_state.evaluation_result_mode = evaluation_mode_label
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')
                finally:
                    if evaluation_visual_index is not None:
                        evaluation_visual_index.close()
                    if evaluation_engine is not None:
                        evaluation_engine.close()

        evaluation_results = st.session_state.get("evaluation_results")
        if evaluation_results is not None:
            evaluation_catalog = {
                item["media_id"]: item for item in MediaCatalog().get_all()
            }
            evaluation_notes = st.text_area(
                t["evaluation_notes"],
                key="evaluation_reviewer_notes",
            )
            marked_results = []
            result_mode = st.session_state.get(
                "evaluation_result_mode", evaluation_mode_label
            )
            results_are_cross_modal = result_mode == t["evaluation_cross_modal"]

            for result_index, result in enumerate(evaluation_results):
                result_type = result.get("result_type", "transcript")
                media_id = (
                    result.get("media_id")
                    if results_are_cross_modal else result["video_id"]
                )
                source_record = evaluation_catalog.get(media_id)
                source_name = (
                    source_record["source_name"] if source_record else media_id[:12]
                )
                if result_type == "keyframe":
                    start = float(result["timestamp_seconds"])
                    end = start
                    identity = f'frame:{result["frame_index"]}'
                else:
                    start = float(
                        result.get("timestamp_seconds", result.get("start", 0.0))
                    )
                    end = (
                        float(result["end"])
                        if "end" in result else start
                    )
                    identity = (
                        f'segment:{result.get("id", result.get("segment_id", result_index))}'
                    )
                result_key = hashlib.sha256(
                    (
                        st.session_state.get("evaluation_result_query", "")
                        + result_type + media_id + identity
                    ).encode("utf-8")
                ).hexdigest()[:16]

                with st.container(border=True):
                    is_relevant = st.checkbox(
                        t["evaluation_relevant"],
                        key=f"evaluation_relevant_{result_key}",
                    )
                    st.markdown(
                        f'**{result_index + 1}. {source_name}** · '
                        f'{t["start"]}: {start:.2f}s'
                    )
                    if result_type == "keyframe":
                        st.caption(
                            f'{t["evaluation_frame_index"]}: {result["frame_index"]}'
                        )
                        image_path = Path(result["image_path"])
                        if image_path.is_file():
                            st.image(str(image_path), use_container_width=True)
                        if "visual_score" in result:
                            st.caption(
                                f'{t["visual_score"]}: {result["visual_score"]:.4f}'
                            )
                    else:
                        st.caption(f'{t["end"]}: {end:.2f}s')
                        if result.get("speaker"):
                            st.caption(f'{t["speaker"]}: {result["speaker"]}')
                        st.write(result.get("original_text", result.get("text", "")))

                    source_path = (
                        Path(source_record["stored_path"])
                        if source_record else None
                    )
                    if source_path and source_path.is_file() and st.button(
                        t["evaluation_play"],
                        key=f"evaluation_play_{result_key}",
                    ):
                        if source_record["media_type"] == "video":
                            st.video(str(source_path), start_time=int(start))
                        else:
                            st.audio(str(source_path), start_time=int(start))

                    if is_relevant:
                        if results_are_cross_modal:
                            if result_type == "keyframe":
                                marked_results.append({
                                    "result_type": "keyframe",
                                    "media_id": media_id,
                                    "frame_index": result["frame_index"],
                                })
                            else:
                                marked_results.append({
                                    "result_type": "transcript",
                                    "media_id": media_id,
                                    "start": result["start"],
                                    "end": result["end"],
                                })
                        else:
                            marked_results.append({
                                "media_id": media_id,
                                "start": start,
                                "end": end,
                            })

            if st.button(
                t["evaluation_save"],
                key="evaluation_save_button",
            ):
                try:
                    if not marked_results:
                        st.warning(t["evaluation_select_relevant"])
                    elif results_are_cross_modal:
                        cross_modal_evaluation_store.add_judgment(
                            st.session_state.get("evaluation_result_query", ""),
                            marked_results,
                            notes=evaluation_notes,
                        )
                        st.success(t["evaluation_cross_modal_saved"])
                    else:
                        evaluation_store.add_judgment(
                            st.session_state.get("evaluation_result_query", ""),
                            marked_results,
                            notes=evaluation_notes,
                        )
                        st.success(t["evaluation_saved"])
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')


    # 8. Timestamped review notes
# --------------------------------------------------

with tab_notes:
    if not has_permission("notes"):
        st.info(t["access_denied"])
    else:
        st.subheader("📝 " + t["archive_notes_title"])
        st.caption(t["archive_notes_desc"])

        note_records = MediaCatalog().get_all()
        if not note_records:
            st.info(t["no_archive_media"])
        else:
            note_catalog = {
                item["media_id"]: item for item in note_records
            }
            note_media_ids = [item["media_id"] for item in note_records]
            current_note_media = st.session_state.get("video_id")
            note_default_index = (
                note_media_ids.index(current_note_media)
                if current_note_media in note_media_ids else 0
            )
            selected_note_media_id = st.selectbox(
                t["archive_notes_media"],
                options=note_media_ids,
                index=note_default_index,
                format_func=lambda media_id: (
                    f'{note_catalog[media_id]["source_name"]} '
                    f'({media_id[:10]})'
                ),
                key="archive_notes_media_select",
            )
            with st.form("archive_note_create_form", clear_on_submit=True):
                new_note_timestamp = st.number_input(
                    t["archive_notes_timestamp"],
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    key="archive_note_new_timestamp",
                )
                new_note_author = st.text_input(
                    t["archive_notes_author"],
                    value="local_user",
                    key="archive_note_new_author",
                )
                new_note_text = st.text_area(
                    t["archive_notes_text"],
                    key="archive_note_new_text",
                    max_chars=ArchiveNotes.MAX_TEXT_LENGTH,
                )
                create_note = st.form_submit_button(
                    t["archive_notes_add"],
                    type="primary",
                )

            if create_note:
                note_manager = ArchiveNotes()
                try:
                    note_manager.add_note(
                        selected_note_media_id,
                        new_note_timestamp,
                        new_note_text,
                        author=new_note_author,
                    )
                    st.success(t["archive_notes_saved"])
                except Exception as error:
                    st.error(f'{t["save_failed"]}: {error}')
                finally:
                    note_manager.close()

            note_manager = ArchiveNotes()
            try:
                media_notes = note_manager.list_notes(selected_note_media_id)
            finally:
                note_manager.close()

            if not media_notes:
                st.info(t["archive_notes_empty"])
            else:
                for note in media_notes:
                    with st.expander(
                        f'{note["timestamp_seconds"]:.2f}s · {note["author"]} · '
                        f'{note["note_text"][:70]}',
                        expanded=False,
                    ):
                        st.caption(
                            f'{t["archive_notes_created"]}: {note["created_at"]} · '
                            f'{t["archive_notes_updated_by"]}: {note["updated_by"]} · '
                            f'Version: {note.get("revision", 1)}'
                        )
                        with st.form(f'archive_note_edit_form_{note["note_id"]}'):
                            edited_timestamp = st.number_input(
                                t["archive_notes_timestamp"],
                                min_value=0.0,
                                value=float(note["timestamp_seconds"]),
                                step=1.0,
                                key=f'archive_note_timestamp_{note["note_id"]}',
                            )
                            edited_text = st.text_area(
                                t["archive_notes_text"],
                                value=note["note_text"],
                                max_chars=ArchiveNotes.MAX_TEXT_LENGTH,
                                key=f'archive_note_text_{note["note_id"]}',
                            )
                            edited_by = st.text_input(
                                t["archive_notes_updated_by"],
                                value="local_user",
                                key=f'archive_note_editor_{note["note_id"]}',
                            )
                            update_note = st.form_submit_button(
                                t["archive_notes_update"]
                            )
                        if update_note:
                            note_manager = ArchiveNotes()
                            try:
                                note_manager.update_note(
                                    note["note_id"],
                                    timestamp_seconds=edited_timestamp,
                                    note_text=edited_text,
                                    updated_by=current_user["username"],
                                    expected_version=note.get("revision", 1),
                                )
                                st.success(t["archive_notes_updated"])
                                st.rerun()
                            except Exception as error:
                                st.error(f'{t["save_failed"]}: {error}')
                            finally:
                                note_manager.close()

                        note_source = note_catalog.get(selected_note_media_id)
                        note_source_path = (
                            Path(note_source["stored_path"])
                            if note_source else None
                        )
                        if note_source_path and note_source_path.is_file() and st.button(
                            t["archive_notes_play"],
                            key=f'archive_note_play_{note["note_id"]}',
                        ):
                            if note_source["media_type"] == "video":
                                st.video(
                                    str(note_source_path),
                                    start_time=int(note["timestamp_seconds"]),
                                )
                            else:
                                st.audio(
                                    str(note_source_path),
                                    start_time=int(note["timestamp_seconds"]),
                                )
                        if st.button(
                            t["archive_notes_delete"],
                            key=f'archive_note_delete_{note["note_id"]}',
                        ):
                            note_manager = ArchiveNotes()
                            try:
                                note_manager.delete_note(
                                    note["note_id"],
                                    actor=current_user["username"],
                                )
                                st.success(t["archive_notes_deleted"])
                                st.rerun()
                            except Exception as error:
                                st.error(f'{t["save_failed"]}: {error}')
                            finally:
                                note_manager.close()


    # 8. Saved clips
# --------------------------------------------------

with tab_clips:
    if not has_permission("clips"):
        st.info(t["access_denied"])
    else:
        st.subheader("🎞️ " + t["clips_title"])
        st.write(t["clips_desc"])

        if not st.session_state.video_id:
            st.info(t["need_video"])
        elif st.session_state.media_type != "video":
            st.info(t["audio_clip_unavailable"])
        else:
            video_id = st.session_state.video_id

            try:
                clips = ClipMetadata().get_all_clips()
            except Exception as error:
                st.error(f'{t["load_clips_failed"]}: {error}')
                clips = []

            current_clips = [
                clip for clip in clips
                if clip.get("video_id") == video_id
            ]

            if current_clips:
                for clip in current_clips:
                    with st.container(border=True):
                        st.markdown(
                            f'**{t["clip"]} {clip["id"]}** · '
                            f'{clip["start"]}s – {clip["end"]}s'
                        )
                        st.caption(clip.get("notes", ""))
                        clip_file = Path(clip["clip_path"])

                        if clip_file.exists():
                            st.video(str(clip_file))
                        else:
                            st.warning(f'{t["missing_clip"]}: {clip_file.name}')

                if st.button(t["export_clips"]):
                    try:
                        clips_csv = ClipExporter.export_csv(
                            current_clips,
                            f"exports/{video_id}_clips.csv",
                        )
                        st.session_state.clips_export_path = str(clips_csv)
                        st.rerun()
                    except Exception as error:
                        st.error(f'{t["export_failed"]}: {error}')

                if st.session_state.clips_export_path:
                    clips_export_path = Path(st.session_state.clips_export_path)
                    if clips_export_path.exists():
                        st.download_button(
                            t["download_clips"],
                            data=clips_export_path.read_bytes(),
                            file_name=clips_export_path.name,
                            mime="text/csv",
                            key=f"download_clips_{video_id}",
                        )
            else:
                st.info(t["no_clips"])


    # 5. Archive organization
# --------------------------------------------------

with tab_archive:
    if not has_permission("archive"):
        st.info(t["access_denied"])
    else:
        st.subheader("🗂️ " + t["archive_title"])
        st.write(t["archive_desc"])

        catalog = MediaCatalog()
        archive_records = catalog.get_all()

        if not archive_records:
            st.info(t["no_archive_items"])
        else:
            labels = {
                f'{item["source_name"]} · {item["media_id"]}': item["media_id"]
                for item in archive_records
            }
            selected_label = st.selectbox(
                t["archive_media"],
                list(labels.keys()),
            )
            selected_media_id = labels[selected_label]
            selected_record = catalog.get_by_id(selected_media_id) or {}

            with st.form("archive_metadata_form"):
                collection_value = st.text_input(
                    t["collection"],
                    value=selected_record.get("collection", ""),
                    placeholder=t["collection_placeholder"],
                    key=f"archive_collection_{selected_media_id}",
                )
                tags_value = st.text_input(
                    t["tags"],
                    value=", ".join(selected_record.get("tags", [])),
                    help=t["tags_help"],
                    key=f"archive_tags_{selected_media_id}",
                )
                save_metadata = st.form_submit_button(t["save_archive_metadata"])

            if save_metadata:
                try:
                    catalog.update_archive_metadata(
                        selected_media_id,
                        collection=collection_value,
                        tags=[
                            tag.strip()
                            for tag in tags_value.split(",")
                            if tag.strip()
                        ],
                    )
                    st.success(t["archive_metadata_saved"])
                    st.rerun()
                except Exception as error:
                    st.error(f'{t["save_failed"]}: {error}')

            st.divider()
            st.markdown(f'### {t["archive_items"]}')
            collection_options = [t["all_collections"]] + catalog.get_collections()
            selected_collection = st.selectbox(
                t["filter_collection"],
                collection_options,
            )
            tag_options = catalog.get_all_tags()
            selected_tags = st.multiselect(
                t["filter_tags"],
                tag_options,
            )
            filtered_records = catalog.filter_media(
                collection=(
                    None if selected_collection == t["all_collections"]
                    else selected_collection
                ),
                tags=selected_tags,
            )
            st.caption(f'{len(filtered_records)} / {len(archive_records)}')
            for item in filtered_records:
                with st.container(border=True):
                    st.markdown(f'**{item["source_name"]}**')
                    st.caption(
                        f'{item["media_type"]} · {item["status"]} · '
                        f'{item.get("collection", t["all_collections"])}'
                    )
                    if item.get("tags"):
                        st.write(" · ".join(item["tags"]))
                    st.caption(item["media_id"])


    # 6. Durable processing queue
# --------------------------------------------------

with tab_queue:
    if not has_permission("queue"):
        st.info(t["access_denied"])
    else:
        st.subheader("⚙️ " + t["queue_title"])
        st.write(t["queue_desc"])
        st.info(t["queue_note"])

        queue = ProcessingQueue()
        with st.form("enqueue_media_folder"):
            input_directory = st.text_input(t["queue_input"])
            add_job = st.form_submit_button(t["queue_add"])

        if add_job:
            candidate = Path(input_directory).expanduser()
            if not input_directory.strip() or not candidate.exists() or not candidate.is_dir():
                st.error(t["queue_path_required"])
            else:
                try:
                    queue.enqueue(
                        "batch_import",
                        {"input_directory": str(candidate.resolve()), "recursive": True},
                        max_attempts=3,
                    )
                    st.success(t["queue_added"])
                    queue.close()
                    st.rerun()
                except Exception as error:
                    st.error(f'{t["queue_failed"]}: {error}')

        if st.button(t["queue_recover"]):
            try:
                recovered = queue.recover_interrupted_jobs(900)
                st.success(f'{t["queue_recovered"]}: {recovered}')
                queue.close()
                st.rerun()
            except Exception as error:
                st.error(f'{t["queue_failed"]}: {error}')

        if st.button(t["queue_run_next"], type="primary"):
            job = queue.claim_next()
            if job is None:
                st.info(t["queue_empty"])
            else:
                try:
                    queue.update_progress(job["job_id"], 5)
                    payload = job["payload"]
                    processor = MediaBatchProcessor()
                    progress_bar = st.progress(0.05)
                    def update_job_progress(done, total):
                        queue.update_progress(
                            job["job_id"],
                            5 + (90 * done / max(total, 1)),
                        )
                        progress_bar.progress(done / max(total, 1))
                        if queue.is_cancel_requested(job["job_id"]):
                            raise RuntimeError("Processing cancellation requested.")

                    def update_job_stage(stage, current_file, stage_progress):
                        queue.update_stage(
                            job["job_id"],
                            stage,
                            current_file=current_file,
                            stage_progress=stage_progress,
                        )

                    results = processor.process_directory(
                        payload["input_directory"],
                        recursive=payload.get("recursive", True),
                        progress_callback=update_job_progress,
                        stage_callback=update_job_stage,
                    )
                    if queue.is_cancel_requested(job["job_id"]):
                        cancelled_job = queue.cancel_running(job["job_id"])
                        st.warning(t["queue_cancel_requested"])
                        queue.close()
                        st.rerun()
                    failures = [item for item in results if item["status"] == "failed"]
                    if failures:
                        detail = "; ".join(
                            f'{item["source"]}: {item.get("error", "unknown error")}'
                            for item in failures
                        )
                        failed_job = queue.fail(job["job_id"], detail)
                        st.error(f'{t["queue_failed"]}: {detail}')
                        st.caption(
                            f'{t["queue_attempts"]}: {failed_job["attempts"]}/'
                            f'{failed_job["max_attempts"]}'
                        )
                    else:
                        queue.update_progress(job["job_id"], 95)
                        queue.complete(job["job_id"])
                        st.success(t["queue_completed"])
                        st.json(results)
                except Exception as error:
                    try:
                        if queue.is_cancel_requested(job["job_id"]):
                            cancelled_job = queue.cancel_running(job["job_id"])
                            st.warning(t["queue_cancel_requested"])
                        else:
                            failed_job = queue.fail(job["job_id"], str(error))
                            st.error(f'{t["queue_failed"]}: {error}')
                            st.caption(
                                f'{t["queue_attempts"]}: {failed_job["attempts"]}/'
                                f'{failed_job["max_attempts"]}'
                            )
                    except Exception:
                        st.error(f'{t["queue_failed"]}: {error}')
                queue.close()
                st.rerun()

        st.divider()
        jobs = queue.list_jobs(limit=50)
        if not jobs:
            st.info(t["queue_empty"])
        for job in jobs:
            with st.container(border=True):
                st.markdown(f'**{job["job_type"]} · {job["job_id"][:12]}**')
                st.caption(job["payload"].get("input_directory", ""))
                st.write(
                    f'{t["queue_status"]}: {job["status"]} · '
                    f'{t["queue_attempts"]}: {job["attempts"]}/{job["max_attempts"]}'
                )
                stage_label = t.get(
                    f'queue_stage_{job.get("stage", "queued")}',
                    job.get("stage", "queued"),
                )
                st.caption(f'{t["queue_stage"]}: {stage_label}')
                if job.get("current_file"):
                    st.caption(f'{t["queue_current_file"]}: {job["current_file"]}')
                st.progress(
                    float(job.get("stage_progress", 0)) / 100,
                    text=(
                        f'{t["queue_stage_progress"]}: '
                        f'{job.get("stage_progress", 0):.0f}%'
                    ),
                )
                st.progress(
                    float(job["progress"]) / 100,
                    text=f'{t["queue_progress"]}: {job["progress"]:.0f}%',
                )
                if job.get("error"):
                    st.error(job["error"])
                action_columns = st.columns(2)
                if job["status"] == "queued":
                    with action_columns[0]:
                        if st.button(t["queue_cancel"], key=f'cancel_{job["job_id"]}'):
                            queue.cancel(job["job_id"])
                            queue.close()
                            st.rerun()
                elif job["status"] == "running":
                    with action_columns[0]:
                        if st.button(t["queue_cancel_requested"], key=f'request_cancel_{job["job_id"]}'):
                            queue.cancel(job["job_id"])
                            queue.close()
                            st.rerun()
                elif job["status"] == "failed":
                    with action_columns[0]:
                        if st.button(t["queue_retry"], key=f'retry_{job["job_id"]}'):
                            queue.retry(job["job_id"])
                            queue.close()
                            st.rerun()

        queue.close()


    # 7. Archive and system dashboard
# --------------------------------------------------

with tab_dashboard:
    if not has_permission("dashboard"):
        st.info(t["access_denied"])
    else:
        st.subheader("📊 " + t["dashboard_title"])
        if st.button(t["dashboard_refresh"]):
            st.rerun()

        metrics = ArchiveMetrics()
        try:
            snapshot = metrics.collect()
            st.caption(f'{t["dashboard_media"]}: {snapshot["media_total"]}')
            summary_columns = st.columns(4)
            summary_columns[0].metric(t["dashboard_media"], snapshot["media_total"])
            summary_columns[1].metric(t["dashboard_videos"], snapshot["video_total"])
            summary_columns[2].metric(t["dashboard_audio"], snapshot["audio_total"])
            summary_columns[3].metric(
                t["dashboard_storage"],
                f'{snapshot["storage_bytes"] / (1024 * 1024):.1f} MB',
            )

            detail_columns = st.columns(3)
            detail_columns[0].metric(
                t["dashboard_transcripts"],
                snapshot["transcript_total"],
            )
            detail_columns[1].metric(
                t["dashboard_missing"],
                snapshot["missing_files"],
            )
            detail_columns[2].metric(
                t["dashboard_db"],
                snapshot["database_health"],
            )

            status_column, queue_column = st.columns(2)
            with status_column:
                st.markdown(f'**{t["dashboard_status"]}**')
                if snapshot["status_counts"]:
                    for status, count in sorted(snapshot["status_counts"].items()):
                        st.write(f"{status}: {count}")
                else:
                    st.caption(t["no_archive_items"])
            with queue_column:
                st.markdown(f'**{t["dashboard_queue"]}**')
                if snapshot["queue_counts"]:
                    for status, count in sorted(snapshot["queue_counts"].items()):
                        st.write(f"{status}: {count}")
                else:
                    st.caption(t["queue_empty"])

            st.divider()
            st.markdown(f'**{t["dashboard_health"]}**')
            health_checks = [
                (t["dashboard_ffmpeg"], snapshot["ffmpeg_available"]),
                (t["dashboard_whisper"], snapshot["faster_whisper_available"]),
                (t["dashboard_semantic"], snapshot["semantic_search_available"]),
                (t["dashboard_visual"], snapshot["visual_search_available"]),
                (t["dashboard_diarization"], snapshot["diarization_available"]),
            ]
            for label, available in health_checks:
                state = t["available"] if available else t["unavailable"]
                st.write(f"{label}: {state}")
        except Exception as error:
            st.error(f'{t["dashboard_title"]}: {error}')
        finally:
            metrics.close()


    # 8. Audit history
# --------------------------------------------------

with tab_audit:
    if not has_permission("audit"):
        st.info(t["access_denied"])
    else:
        st.subheader("🧾 " + t["audit_title"])
        actor_filter = st.text_input(t["audit_actor"], key="audit_actor_filter")
        entity_filter = st.selectbox(
            t["audit_entity"],
            [t["audit_all"], "media", "processing_job"],
            key="audit_entity_filter",
        )
        audit_log = AuditLog()
        try:
            events = audit_log.list_events(
                limit=200,
                entity_type=None if entity_filter == t["audit_all"] else entity_filter,
                actor=actor_filter.strip() or None,
            )
            if not events:
                st.info(t["audit_empty"])
            for event in events:
                with st.container(border=True):
                    st.markdown(
                        f'**{event["action"]}** · {event["entity_type"]} · '
                        f'{event["entity_id"][:16]}'
                    )
                    st.caption(
                        f'{event["occurred_at"]} UTC · {t["audit_actor"]}: '
                        f'{event["actor"]}'
                    )
                    with st.expander(t["audit_details"]):
                        st.json(event["details"])
        except Exception as error:
            st.error(f'{t["audit_title"]}: {error}')
        finally:
            audit_log.close()


# --------------------------------------------------
# 13. User management
# --------------------------------------------------

with tab_users:
    if not auth_enabled:
        st.info(t["auth_disabled"])
    elif not has_permission("users"):
        st.info(t["access_denied"])
    else:
        st.subheader("👥 " + t["user_management_title"])
        with st.form("archive_create_user_form", clear_on_submit=True):
            new_username = st.text_input(t["username"], key="archive_new_username")
            new_display_name = st.text_input(
                t["display_name"],
                key="archive_new_display_name",
            )
            new_user_password = st.text_input(
                t["password"],
                type="password",
                key="archive_new_user_password",
            )
            new_user_role = st.selectbox(
                t["select_role"],
                options=["editor", "search_only", "administrator"],
                format_func=lambda role: t[f"role_{role}"],
                key="archive_new_user_role",
            )
            create_user_submitted = st.form_submit_button(
                t["create_user"],
                type="primary",
            )
        if create_user_submitted:
            try:
                auth_manager.create_user(
                    new_username,
                    new_user_password,
                    display_name=new_display_name or new_username,
                    role=new_user_role,
                    actor=current_user["username"],
                )
                st.success(t["user_created"])
                st.rerun()
            except Exception as error:
                st.error(str(error))

        user_records = auth_manager.list_users()
        if user_records:
            st.dataframe(
                [
                    {
                        t["username"]: user["username"],
                        t["display_name"]: user["display_name"],
                        t["select_role"]: t[f'role_{user["role"]}'],
                        t["active"]: user["is_active"],
                    }
                    for user in user_records
                ],
                use_container_width=True,
                hide_index=True,
            )
            user_names = [user["username"] for user in user_records]
            selected_user_name = st.selectbox(
                t["users"],
                options=user_names,
                key="archive_manage_user_select",
            )
            selected_user = next(
                user for user in user_records
                if user["username"] == selected_user_name
            )
            with st.form("archive_update_user_form"):
                updated_role = st.selectbox(
                    t["select_role"],
                    options=["administrator", "editor", "search_only"],
                    index=["administrator", "editor", "search_only"].index(
                        selected_user["role"]
                    ),
                    format_func=lambda role: t[f"role_{role}"],
                )
                updated_active = st.checkbox(
                    t["active"],
                    value=selected_user["is_active"],
                )
                update_user_submitted = st.form_submit_button(t["update_user"])
            if update_user_submitted:
                try:
                    if updated_role != selected_user["role"]:
                        auth_manager.update_user_role(
                            selected_user_name,
                            updated_role,
                            actor=current_user["username"],
                        )
                    if updated_active != selected_user["is_active"]:
                        auth_manager.set_user_active(
                            selected_user_name,
                            updated_active,
                            actor=current_user["username"],
                        )
                    st.success(t["user_updated"])
                    st.rerun()
                except Exception as error:
                    st.error(str(error))

            with st.form("archive_reset_user_password_form"):
                reset_password_value = st.text_input(
                    t["new_password"],
                    type="password",
                )
                reset_password_submitted = st.form_submit_button(
                    t["reset_user_password"]
                )
            if reset_password_submitted:
                try:
                    auth_manager.reset_password(
                        selected_user_name,
                        reset_password_value,
                        actor=current_user["username"],
                    )
                    st.success(t["user_password_reset"])
                except Exception as error:
                    st.error(str(error))


# --------------------------------------------------
# Footer
# --------------------------------------------------

st.divider()
st.caption(f'🎓 {t["footer"]}')
