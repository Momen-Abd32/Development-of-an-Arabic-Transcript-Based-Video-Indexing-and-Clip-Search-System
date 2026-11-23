import hashlib
import os
import tempfile
from pathlib import Path

import streamlit as st

from src.media.audio_extractor import AudioExtractor
from src.media.audit_log import AuditLog
from src.media.media_catalog import MediaCatalog
from src.media.keyframe_extractor import KeyframeExtractor
from src.media.processing_queue import ProcessingQueue
from src.media.batch_processor import MediaBatchProcessor
from src.media.archive_metrics import ArchiveMetrics
from src.transcription.faster_whisper_engine import FasterWhisperEngine
from src.transcription.transcript_manager import TranscriptManager
from src.transcription.speaker_diarizer import PyannoteSpeakerDiarizer
from src.transcription.transcript_insights import TranscriptInsights
from src.transcription.transcript_exporter import TranscriptExporter
from src.indexing.indexer import TranscriptIndexer
from src.search.search_engine import SearchEngine
from src.search.cross_modal_search import CrossModalSearch
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
        "speaker_diarization_help": "تتطلب هذه الميزة تثبيت requirements-diarization.txt وإعداد HF_TOKEN مع صلاحية الوصول إلى نموذج pyannote.",
        "speaker": "المتحدث",
        "generate_insights": "إنشاء ملخص واستخراج الكلمات المفتاحية",
        "insights_saved": "تم إنشاء وحفظ الملخص والكلمات المفتاحية.",
        "insights_title": "ملخص استخراجي",
        "keywords_title": "الكلمات المفتاحية",
        "extractive_note": "هذا ملخص استخراجي مكوّن من جمل أصلية من التفريغ؛ لا يعيد صياغة الكلام أو يحوّل اللهجة إلى الفصحى.",
        "extract_keyframes": "استخراج الصور المصغّرة من الفيديو",
        "keyframes_done": "تم استخراج الصور المصغّرة.",
        "extracting_keyframes": "جاري استخراج الصور المصغّرة...",
        "keyframes_failed": "تعذر استخراج الصور المصغّرة",
        "keyframes_title": "الصور المصغّرة / اللقطات الرئيسية",
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
        "speaker_diarization_help": "Requires requirements-diarization.txt, HF_TOKEN, and access to the pyannote model.",
        "speaker": "Speaker",
        "generate_insights": "Generate Summary and Keywords",
        "insights_saved": "Summary and keywords generated and saved.",
        "insights_title": "Extractive Summary",
        "keywords_title": "Keywords",
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

tab_upload, tab_transcript, tab_search, tab_visual, tab_cross_modal, tab_clips, tab_archive, tab_queue, tab_dashboard, tab_audit = st.tabs(
    [
        t["upload_tab"], t["transcript_tab"], t["search_tab"],
        t["visual_search_tab"], t["cross_modal_tab"], t["clips_tab"], t["archive_tab"],
        t["queue_tab"], t["dashboard_tab"], t["audit_tab"],
    ]
)


# --------------------------------------------------
# 1. Media upload and transcription

with tab_upload:
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
                    diarizer = PyannoteSpeakerDiarizer()
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
            if current_insights["keywords"]:
                st.markdown(f'**{t["keywords_title"]}**')
                st.write(", ".join(item["term"] for item in current_insights["keywords"]))

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

                edited_segments.append({
                    "start": segment["start"],
                    "end": segment["end"],
                    "text": edited_text,
                    **({"speaker": segment["speaker"]} if segment.get("speaker") else {}),
                })

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
                        except RuntimeError as provider_error:
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
                st.caption(" + ".join(result["matched_by"]))
                if result["result_type"] == "keyframe":
                    frame_path = Path(result["image_path"])
                    if frame_path.is_file():
                        st.image(str(frame_path), use_container_width=True)
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


# 6. Saved clips
# --------------------------------------------------

with tab_clips:
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

                results = processor.process_directory(
                    payload["input_directory"],
                    recursive=payload.get("recursive", True),
                    progress_callback=update_job_progress,
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
# Footer
# --------------------------------------------------

st.divider()
st.caption(f'🎓 {t["footer"]}')
