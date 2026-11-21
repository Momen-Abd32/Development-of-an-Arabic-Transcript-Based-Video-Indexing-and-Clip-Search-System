import hashlib
from pathlib import Path

import streamlit as st

from src.media.audio_extractor import AudioExtractor
from src.transcription.faster_whisper_engine import FasterWhisperEngine
from src.transcription.transcript_manager import TranscriptManager
from src.transcription.transcript_exporter import TranscriptExporter
from src.indexing.indexer import TranscriptIndexer
from src.search.search_engine import SearchEngine
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

tab_upload, tab_transcript, tab_search, tab_clips = st.tabs(
    [t["upload_tab"], t["transcript_tab"], t["search_tab"], t["clips_tab"]]
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

                if not media_path.exists():
                    with media_path.open("wb") as output_file:
                        output_file.write(file_buffer)
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

            st.session_state.media_path = str(media_path)
            st.session_state.media_type = media_type
            st.session_state.video_path = (
                str(media_path) if media_type == "video" else None
            )
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
            with st.spinner(t["extracting_audio"]):
                AudioExtractor.prepare(str(media_path), str(audio_path))

            with st.spinner(t["loading_model"]):
                engine = FasterWhisperEngine(model_size="tiny")
                segments = engine.transcribe(str(audio_path))

            TranscriptManager.save(
                segments,
                f"data/transcripts/{media_id}.json",
            )

            indexer = TranscriptIndexer()
            try:
                indexer.index_segments(media_id, segments)
            finally:
                indexer.close()

            st.session_state.segments = segments
            st.session_state.transcribed = True
            st.session_state.search_results = []
            st.session_state.transcript_export_path = None
            st.success(f'{t["transcription_done"]}: {len(segments)}')
            st.rerun()

        except Exception as error:
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

        for index, segment in enumerate(st.session_state.segments):
            with st.container(border=True):
                time_col, text_col = st.columns([1.5, 5])
                with time_col:
                    st.caption(f'{t["start"]}: {segment["start"]}s')
                    st.caption(f'{t["end"]}: {segment["end"]}s')
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
                })

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
# --------------------------------------------------

with tab_search:
    st.subheader("🔎 " + t["search_title"])
    st.write(t["search_desc"])

    if not st.session_state.transcribed:
        st.info(t["no_transcript"])
    else:
        video_id = st.session_state.video_id

        query = st.text_input(t["query"], key=f"search_query_{video_id}")
        search_type = st.radio(
            t["search_type"],
            [t["exact"], t["fuzzy"]],
            horizontal=True,
            key=f"search_type_{video_id}",
        )

        if st.button(t["search_button"], type="primary"):
            if not query.strip():
                st.warning(t["empty_query"])
            else:
                search_engine = None
                try:
                    search_engine = SearchEngine()
                    if search_type == t["exact"]:
                        results = search_engine.exact_search(query, video_id=video_id)
                    else:
                        results = search_engine.fuzzy_search(query, video_id=video_id)

                    st.session_state.search_results = results
                except Exception as error:
                    st.error(f'{t["search_failed"]}: {error}')
                finally:
                    if search_engine is not None:
                        search_engine.close()

        st.caption(t["duration_note"])

        if st.session_state.search_results:
            st.markdown(f"### {t['results']} ({len(st.session_state.search_results)})")

            for result in st.session_state.search_results:
                with st.container(border=True):
                    st.markdown(f'**{t["text"]}:** {result["original_text"]}')
                    st.markdown(
                        f'**{t["time"]}:** {result["start"]}s – {result["end"]}s'
                    )
                    if "similarity" in result:
                        st.progress(
                            max(0, min(100, int(result["similarity"]))) / 100,
                            text=f'{t["similarity"]}: {result["similarity"]}%',
                        )

                    if st.session_state.media_type == "video":
                        if st.button(
                            "✂️ " + t["save_clip"],
                            key=f"save_clip_{video_id}_{result['id']}",
                        ):
                            try:
                                clip_path = ClipManager().create_clip(
                                    st.session_state.video_path,
                                    result["start"],
                                    result["end"],
                                    f"{video_id}_clip_{result['id']}",
                                )
                                ClipMetadata().save_clip(
                                    video_id,
                                    str(clip_path),
                                    result["start"],
                                    result["end"],
                                    result["original_text"],
                                )
                                st.success(t["clip_saved"])
                            except Exception as error:
                                st.error(f'{t["clip_failed"]}: {error}')
                    else:
                        st.caption(t["audio_clip_unavailable"])
        else:
            st.info(t["no_results"])


# --------------------------------------------------
# 4. Saved clips
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


# --------------------------------------------------
# Footer
# --------------------------------------------------

st.divider()
st.caption(f'🎓 {t["footer"]}')
