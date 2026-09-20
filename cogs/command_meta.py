"""Central command metadata for the dashboard and command help surfaces.

This module intentionally contains data only.  It must remain safe to import
without loading Discord cogs, opening the database, or performing I/O.
"""

from __future__ import annotations

from copy import deepcopy


COMMAND_CATEGORIES = (
    "الطرد والحظر",
    "الإسكات والصوت",
    "إدارة الشات",
    "Blacklist القنوات",
    "الأمان — السجن",
    "التحذيرات والإدارة",
    "أوامر الأعضاء — معلومات",
    "أوامر الأعضاء — أدوات",
    "إدارة القنوات",
    "أوامر متقدمة",
    "السجل والملاحظات",
    "إحصائيات وتراجع",
)

AUTO_DELETE_PRESETS = (0, 5, 10, 30, 60, 300)
RESPONSE_STYLES = ("default", "embed", "compact", "silent")


def _command(
    key: str,
    display_name: str,
    category: str,
    required_permission: str,
    aliases: list[str],
    syntax: str,
    example: str,
    description: str,
) -> dict:
    return {
        "key": key,
        "display_name": display_name,
        "category": category,
        "required_permission": required_permission,
        "default_aliases": list(aliases),
        "syntax": syntax,
        "example": example,
        "description": description,
    }


_COMMAND_SPECS = {
    # الطرد والحظر
    "kick": ("طرد (Kick)", "الطرد والحظر", "kick_members", ["k", "طرد", "زوووط", "دزمها"], "!kick @عضو [السبب]", "!kick @أحمد السلوك السيء", "طرد عضو من السيرفر مع تسجيل السبب وإبلاغ العضو بالإجراء."),
    "ban": ("حظر (Ban)", "الطرد والحظر", "ban_members", ["b", "حظر"], "!ban @عضو [السبب]", "!ban @أحمد إساءة متكررة", "حظر عضو من السيرفر ومنعه من العودة وفق صلاحيات Discord."),
    "tempban": ("حظر مؤقت (Tempban)", "الطرد والحظر", "ban_members", ["tb", "حظر_مؤقت"], "!tempban @عضو [المدة] [السبب]", "!tempban @أحمد 7d تحذير أخير", "حظر عضو لمدة محددة ثم رفع الحظر تلقائياً عند انتهاء المدة."),
    "unban": ("فك الحظر (Unban)", "الطرد والحظر", "ban_members", ["ub", "فك_الحظر"], "!unban [معرف العضو]", "!unban 123456789012345678", "رفع الحظر عن عضو باستخدام معرف Discord الخاص به."),
    "softban": ("حظر ناعم (Softban)", "الطرد والحظر", "ban_members", ["soft"], "!softban @عضو [السبب]", "!softban @أحمد تنظيف الرسائل", "طرد العضو وحذف رسائله الحديثة ثم السماح له بالعودة."),
    "massban": ("حظر جماعي (Massban)", "الطرد والحظر", "ban_members", ["mb"], "!massban [الأعضاء]", "!massban @عضو1 @عضو2", "تنفيذ حظر جماعي بعد التحقق من الصلاحيات والتأكيد."),
    "masskick": ("طرد جماعي (Masskick)", "الطرد والحظر", "kick_members", ["mk"], "!masskick [الأعضاء]", "!masskick @عضو1 @عضو2", "تنفيذ طرد جماعي للأعضاء المحددين بعد تأكيد العملية."),
    # الإسكات والصوت
    "timeout": ("تايم أوت (Timeout)", "الإسكات والصوت", "moderate_members", ["to", "تايم"], "!timeout @عضو [الدقائق] [السبب]", "!timeout @أحمد 30 إزعاج", "إسكات عضو لمدة محددة باستخدام نظام Timeout الرسمي في Discord."),
    "untimeout": ("فك التايم أوت (Untimeout)", "الإسكات والصوت", "moderate_members", ["uto"], "!untimeout @عضو", "!untimeout @أحمد", "إزالة حالة Timeout والسماح للعضو بالتحدث مجدداً."),
    "mute": ("إسكات (Mute)", "الإسكات والصوت", "moderate_members", ["m", "اسكت"], "!mute @عضو [المدة] [السبب]", "!mute @أحمد 10m إزعاج", "إسكات عضو وفق إعدادات السيرفر مع حفظ مدة الإجراء وسببه."),
    "unmute": ("فك الإسكات (Unmute)", "الإسكات والصوت", "moderate_members", ["um"], "!unmute @عضو", "!unmute @أحمد", "إلغاء إسكات العضو وإعادة صلاحية التحدث له."),
    "voice_mute": ("كتم صوتي (Voice Mute)", "الإسكات والصوت", "mute_members", ["vmute"], "!voice_mute @عضو [السبب]", "!voice_mute @أحمد ضوضاء", "كتم صوت عضو داخل القناة الصوتية الحالية."),
    "voice_unmute": ("فك كتم صوتي (Voice Unmute)", "الإسكات والصوت", "mute_members", ["vunmute"], "!voice_unmute @عضو", "!voice_unmute @أحمد", "إلغاء الكتم الصوتي عن عضو داخل القناة."),
    "voice_move": ("نقل صوتي (Voice Move)", "الإسكات والصوت", "move_members", ["vmove"], "!voice_move @عضو [القناة]", "!voice_move @أحمد غرفة-1", "نقل عضو إلى قناة صوتية يحددها المشرف."),
    "voice_disconnect": ("فصل صوتي (Voice Disconnect)", "الإسكات والصوت", "move_members", ["vdc"], "!voice_disconnect @عضو", "!voice_disconnect @أحمد", "إخراج عضو من القناة الصوتية الحالية."),
    "radio": ("إذاعة (Radio)", "الإسكات والصوت", "connect", ["راديو"], "!radio", "!radio", "تشغيل البث الصوتي المباشر داخل القناة الصوتية."),
    "stop_radio": ("إيقاف الإذاعة (Stop Radio)", "الإسكات والصوت", "connect", ["إيقاف_الراديو"], "!stop_radio", "!stop_radio", "إيقاف البث الصوتي وفصل البوت من القناة."),
    # إدارة الشات
    "clear": ("مسح (Clear)", "إدارة الشات", "manage_messages", ["c", "مسح", "purge"], "!clear [العدد]", "!clear 50", "حذف عدد محدد من رسائل القناة مع احترام حدود Discord."),
    "purge": ("تنظيف شامل (Purge)", "إدارة الشات", "manage_messages", ["تنظيف"], "!purge [العدد]", "!purge 100", "تنظيف دفعة كبيرة من الرسائل بعد تأكيد المشرف."),
    "say": ("رسالة رسمية (Say)", "إدارة الشات", "manage_messages", ["قل"], "!say [النص]", "!say سيتم إغلاق القناة للصيانة", "إرسال رسالة باسم البوت بعد التحقق من صلاحية إدارة الرسائل."),
    "announce": ("إعلان (Announce)", "إدارة الشات", "manage_messages", ["إعلان"], "!announce [العنوان] [النص]", "!announce تحديث السيرفر تم إطلاق الموسم الجديد", "نشر إعلان منسق في القناة الحالية."),
    "embed": ("رسالة Embed", "إدارة الشات", "manage_messages", ["إمبد"], "!embed [العنوان] | [النص]", "!embed القوانين | يرجى قراءة القوانين قبل المشاركة", "إنشاء رسالة Embed منسقة وقابلة للقراءة."),
    "react": ("تفاعل (React)", "إدارة الشات", "manage_messages", ["تفاعل"], "!react [الإيموجي]", "!react ✅", "إضافة تفاعل إلى آخر رسالة في القناة."),
    "poll": ("استطلاع (Poll)", "إدارة الشات", "manage_messages", ["تصويت", "استطلاع"], "!poll [السؤال] | [الخيارات]", "!poll أفضل لعبة؟ | Valorant | FIFA", "إنشاء استطلاع تفاعلي مع أزرار ونسب مئوية مباشرة."),
    "slowmode": ("الوضع البطيء (Slowmode)", "إدارة الشات", "manage_channels", ["بطء"], "!slowmode [الثواني]", "!slowmode 10", "تعيين الفاصل الزمني بين رسائل الأعضاء في القناة."),
    "slowmode_off": ("إلغاء الوضع البطيء (Slowmode Off)", "إدارة الشات", "manage_channels", ["إلغاء_البطء"], "!slowmode_off", "!slowmode_off", "إلغاء الوضع البطيء وإعادة القناة إلى الإرسال الطبيعي."),
    "lockdown": ("قفل الشات (Lockdown)", "إدارة الشات", "manage_channels", ["lock", "قفل"], "!lockdown [تشغيل/إيقاف]", "!lockdown true", "قفل أو فتح الكتابة في القناة للأعضاء غير المشرفين."),
    "lock": ("قفل القناة (Lock)", "إدارة الشات", "manage_channels", ["قفل"], "!lock [القناة]", "!lock #الإعلانات", "منع الأعضاء من الكتابة في قناة محددة."),
    "unlock": ("فتح القناة (Unlock)", "إدارة الشات", "manage_channels", ["فتح"], "!unlock [القناة]", "!unlock #الإعلانات", "إعادة السماح للأعضاء بالكتابة في القناة."),
    "thread_lock": ("قفل المحادثة (Thread Lock)", "إدارة الشات", "manage_threads", ["قفل_ثريد"], "!thread_lock", "!thread_lock", "قفل المحادثة الفرعية الحالية ومنع الردود الجديدة."),
    "thread_unlock": ("فتح المحادثة (Thread Unlock)", "إدارة الشات", "manage_threads", ["فتح_ثريد"], "!thread_unlock", "!thread_unlock", "فتح المحادثة الفرعية الحالية للسماح بالردود."),
    # Blacklist القنوات
    "blacklist": ("حظر القنوات (Blacklist)", "Blacklist القنوات", "manage_channels", ["بلوك", "بلاكليست"], "!blacklist [القناة]", "!blacklist #الدردشة", "إضافة قناة إلى قائمة القنوات المحظورة من استخدام أوامر محددة."),
    "unblacklist": ("إزالة حظر القناة (Unblacklist)", "Blacklist القنوات", "manage_channels", ["فك_البلوك"], "!unblacklist [القناة]", "!unblacklist #الدردشة", "إزالة القناة من قائمة القنوات المحظورة."),
    "blacklist_list": ("قائمة الحظر (Blacklist List)", "Blacklist القنوات", "manage_channels", ["قائمة_البلوك"], "!blacklist_list", "!blacklist_list", "عرض القنوات الموجودة حالياً في قائمة الحظر."),
    "channelinfo": ("معلومات القناة (Channel Info)", "Blacklist القنوات", "manage_channels", ["معلومات_القناة"], "!channelinfo [القناة]", "!channelinfo #الدردشة", "عرض معرف القناة وصلاحياتها وإعداداتها الأساسية."),
    # الأمان — السجن
    "jail": ("السجن (Jail)", "الأمان — السجن", "administrator", ["سجن"], "!jail @عضو [السبب]", "!jail @أحمد تخريب", "نقل العضو إلى نظام السجن ومنعه من الوصول إلى القنوات العامة."),
    "unjail": ("فك السجن (Unjail)", "الأمان — السجن", "administrator", ["فك_السجن"], "!unjail @عضو", "!unjail @أحمد", "إخراج العضو من السجن وإعادة صلاحياته السابقة."),
    "jail_setup": ("تهيئة السجن (Jail Setup)", "الأمان — السجن", "administrator", ["تهيئة_السجن"], "!jail_setup", "!jail_setup", "تهيئة رتبة وقناة السجن في السيرفر بشكل آمن."),
    "setup_captcha": ("بوابة التحقق (Captcha)", "الأمان — السجن", "administrator", ["كابتشا", "تحقق"], "!setup_captcha", "!setup_captcha", "تثبيت بوابة تحقق بشرية للأعضاء الجدد."),
    "anti_nuke": ("الحماية من التخريب (Anti-Nuke)", "الأمان — السجن", "administrator", ["حماية"], "!anti_nuke [تشغيل/إيقاف]", "!anti_nuke true", "تفعيل أو تعطيل طبقة الحماية من عمليات التخريب الجماعي."),
    "security_status": ("حالة الأمان (Security Status)", "الأمان — السجن", "administrator", ["حالة_الأمان"], "!security_status", "!security_status", "عرض حالة طبقات الحماية والحوادث الأمنية الأخيرة."),
    "audit": ("تدقيق الأمان (Audit)", "الأمان — السجن", "view_audit_log", ["تدقيق"], "!audit [العدد]", "!audit 20", "عرض آخر أحداث سجل Discord مع تنسيق قابل للمراجعة."),
    # التحذيرات والإدارة
    "warn": ("تحذير (Warn)", "التحذيرات والإدارة", "kick_members", ["w", "تحذير", "عيب"], "!warn @عضو [السبب]", "!warn @أحمد لغة غير لائقة", "إضافة تحذير موثق إلى سجل العضو وإبلاغه بالسبب."),
    "warnings": ("سجل التحذيرات (Warnings)", "التحذيرات والإدارة", "kick_members", ["تحذيرات", "سجل"], "!warnings @عضو", "!warnings @أحمد", "عرض أرشيف تحذيرات عضو مع أرقام السجلات."),
    "unwarn": ("إلغاء تحذير (Unwarn)", "التحذيرات والإدارة", "kick_members", ["حذف_تحذير"], "!unwarn [رقم السجل]", "!unwarn 42", "إلغاء تحذير محفوظ باستخدام رقم السجل."),
    "case": ("ملف الإجراء (Case)", "التحذيرات والإدارة", "kick_members", ["حالة"], "!case [رقم السجل]", "!case 42", "عرض تفاصيل إجراء إداري واحد من سجل السيرفر."),
    "modlogs": ("سجل الإدارة (Modlogs)", "التحذيرات والإدارة", "view_audit_log", ["سجل_الإدارة"], "!modlogs [العدد]", "!modlogs 25", "عرض الإجراءات الإدارية الأخيرة للمتابعة والمراجعة."),
    "note": ("ملاحظة عضو (Note)", "التحذيرات والإدارة", "manage_messages", ["ملاحظة"], "!note @عضو [النص]", "!note @أحمد يحتاج متابعة", "حفظ ملاحظة داخلية عن عضو دون إرسالها له."),
    "notes": ("ملاحظات العضو (Notes)", "التحذيرات والإدارة", "manage_messages", ["ملاحظات"], "!notes @عضو", "!notes @أحمد", "عرض الملاحظات الداخلية المحفوظة لعضو."),
    "role": ("إدارة رتبة (Role)", "التحذيرات والإدارة", "manage_roles", ["رتبة"], "!role @عضو [الرتبة]", "!role @أحمد VIP", "إضافة رتبة إلى عضو بعد التحقق من ترتيب الرتب."),
    "addrole": ("إضافة رتبة (Add Role)", "التحذيرات والإدارة", "manage_roles", ["إضافة_رتبة"], "!addrole @عضو [الرتبة]", "!addrole @أحمد VIP", "إضافة رتبة واحدة أو أكثر إلى عضو."),
    "removerole": ("إزالة رتبة (Remove Role)", "التحذيرات والإدارة", "manage_roles", ["إزالة_رتبة"], "!removerole @عضو [الرتبة]", "!removerole @أحمد VIP", "إزالة رتبة من عضو بعد فحص صلاحيات البوت."),
    "massrole": ("رتبة جماعية (Mass Role)", "التحذيرات والإدارة", "manage_roles", ["mr"], "!massrole [الرتبة] [الأعضاء]", "!massrole VIP @أحمد @سالم", "تطبيق رتبة على مجموعة أعضاء بعد تأكيد العملية."),
    # أوامر الأعضاء — معلومات
    "help": ("المساعدة (Help)", "أوامر الأعضاء — معلومات", "send_messages", ["مساعدة", "اوامر"], "!help [القسم]", "!help moderation", "عرض دليل أوامر PRIME وأقسامها وطريقة استخدامها."),
    "status": ("الحالة (Status)", "أوامر الأعضاء — معلومات", "send_messages", ["حالة"], "!status", "!status", "عرض صحة البوت والاتصال والخدمات والسيرفرات المتصلة."),
    "ping": ("اختبار الاتصال (Ping)", "أوامر الأعضاء — معلومات", "send_messages", ["بنق"], "!ping", "!ping", "قياس زمن استجابة Discord وزمن معالجة الطلب."),
    "serverinfo": ("معلومات السيرفر (Server Info)", "أوامر الأعضاء — معلومات", "send_messages", ["سيرفر"], "!serverinfo", "!serverinfo", "عرض بيانات السيرفر وعدد الأعضاء والقنوات والرتب."),
    "userinfo": ("معلومات العضو (User Info)", "أوامر الأعضاء — معلومات", "send_messages", ["عضو"], "!userinfo @عضو", "!userinfo @أحمد", "عرض معلومات عضو عامة مثل المعرف وتاريخ الانضمام والرتب."),
    "memberinfo": ("ملف العضو (Member Info)", "أوامر الأعضاء — معلومات", "send_messages", ["ملف"], "!memberinfo @عضو", "!memberinfo @أحمد", "عرض بطاقة معلومات تفصيلية لعضو في السيرفر."),
    "avatar": ("الصورة الشخصية (Avatar)", "أوامر الأعضاء — معلومات", "send_messages", ["صورة"], "!avatar [العضو]", "!avatar @أحمد", "عرض الصورة الشخصية لعضو بالحجم الكامل."),
    "roleinfo": ("معلومات الرتبة (Role Info)", "أوامر الأعضاء — معلومات", "send_messages", ["معلومات_رتبة"], "!roleinfo [الرتبة]", "!roleinfo VIP", "عرض معلومات الرتبة وعدد أعضائها وترتيبها."),
    "emojiinfo": ("معلومات الإيموجي (Emoji Info)", "أوامر الأعضاء — معلومات", "send_messages", ["معلومات_ايموجي"], "!emojiinfo [الإيموجي]", "!emojiinfo :prime:", "عرض معرف الإيموجي ونوعه ورابطه."),
    "channelinfo": ("معلومات القناة (Channel Info)", "أوامر الأعضاء — معلومات", "send_messages", ["معلومات_القناة"], "!channelinfo [القناة]", "!channelinfo #الدردشة", "عرض معلومات القناة الحالية أو قناة يحددها العضو."),
    "botinfo": ("معلومات البوت (Bot Info)", "أوامر الأعضاء — معلومات", "send_messages", ["معلومات_البوت"], "!botinfo", "!botinfo", "عرض إصدار البوت ووقت تشغيله وعدد أوامره."),
    "invite": ("دعوة البوت (Invite)", "أوامر الأعضاء — معلومات", "send_messages", ["دعوة"], "!invite", "!invite", "إنشاء رابط دعوة البوت بالصلاحيات المعلنة."),
    "rules": ("القوانين (Rules)", "أوامر الأعضاء — معلومات", "send_messages", ["قوانين"], "!rules", "!rules", "عرض قوانين السيرفر المنشورة للأعضاء."),
    # أوامر الأعضاء — أدوات
    "profile": ("الملف الشخصي (Profile)", "أوامر الأعضاء — أدوات", "send_messages", ["بروفايل", "ملفي"], "!profile [العضو]", "!profile @أحمد", "عرض ملف العضو ومستواه ومحفظته وإحصائيات نشاطه."),
    "daily": ("المكافأة اليومية (Daily)", "أوامر الأعضاء — أدوات", "send_messages", ["يومي"], "!daily", "!daily", "منح المكافأة اليومية للمستخدم مرة كل فترة استحقاق."),
    "راتب": ("الراتب (Salary)", "أوامر الأعضاء — أدوات", "send_messages", ["راتب", "يومي"], "!راتب", "!راتب", "اختصار عربي لاستلام المكافأة اليومية."),
    "work": ("العمل (Work)", "أوامر الأعضاء — أدوات", "send_messages", ["عمل"], "!work", "!work", "تنفيذ نشاط العمل ومنح عائد اقتصادي عشوائي آمن."),
    "pay": ("الدفع (Pay)", "أوامر الأعضاء — أدوات", "send_messages", ["تحويل"], "!pay @عضو [المبلغ]", "!pay @أحمد 500", "تحويل مبلغ من محفظة المستخدم إلى عضو آخر."),
    "deposit": ("الإيداع (Deposit)", "أوامر الأعضاء — أدوات", "send_messages", ["إيداع"], "!deposit [المبلغ]", "!deposit 500", "إيداع المال من المحفظة في الحساب البنكي."),
    "withdraw": ("السحب (Withdraw)", "أوامر الأعضاء — أدوات", "send_messages", ["سحب"], "!withdraw [المبلغ]", "!withdraw 250", "سحب المال من الحساب البنكي إلى المحفظة."),
    "rob": ("المخاطرة (Rob)", "أوامر الأعضاء — أدوات", "send_messages", ["سرقة"], "!rob @عضو", "!rob @أحمد", "محاولة سرقة اقتصادية بمخاطرة واحتمال عقوبة."),
    "leaderboard": ("المتصدرون (Leaderboard)", "أوامر الأعضاء — أدوات", "send_messages", ["توب", "متصدرين"], "!leaderboard [النوع]", "!leaderboard wealth", "عرض ترتيب أعضاء السيرفر حسب الثروة أو المستوى."),
    "giveaway": ("السحب (Giveaway)", "أوامر الأعضاء — أدوات", "manage_events", ["سحب", "قرعة"], "!giveaway [المدة] [الجائزة]", "!giveaway 60m رتبة VIP", "إطلاق سحب مؤقت واختيار فائز من المشاركين."),
    "remind": ("تذكير (Remind)", "أوامر الأعضاء — أدوات", "send_messages", ["ذكرني"], "!remind [المدة] [النص]", "!remind 30m راجع البطولة", "حفظ تذكير شخصي وإرساله عند حلول موعده."),
    "reminders": ("تذكيراتي (Reminders)", "أوامر الأعضاء — أدوات", "send_messages", ["تذكيراتي"], "!reminders", "!reminders", "عرض التذكيرات المحفوظة للمستخدم في السيرفر."),
    "reminder_cancel": ("إلغاء تذكير (Reminder Cancel)", "أوامر الأعضاء — أدوات", "send_messages", ["إلغاء_تذكير"], "!reminder_cancel [المعرف]", "!reminder_cancel 12", "إلغاء تذكير محفوظ قبل موعده."),
    "ask": ("اسأل PRIME (Ask)", "أوامر الأعضاء — أدوات", "send_messages", ["سؤال"], "!ask [السؤال]", "!ask كيف أرفع مستوى الأمان؟", "طرح سؤال أو طلب مساعدة ذكية من البوت."),
    "ask_ai": ("الذكاء الاصطناعي (Ask AI)", "أوامر الأعضاء — أدوات", "send_messages", ["ai", "ذكاء"], "!ask_ai [السؤال]", "!ask_ai اشرح لي هذه القاعدة", "إرسال سؤال إلى مساعد الذكاء الاصطناعي للحصول على إجابة تحليلية."),
    "imagine": ("توليد صورة (Imagine)", "أوامر الأعضاء — أدوات", "send_messages", ["صورة_ai"], "!imagine [الوصف]", "!imagine مدينة مستقبلية ليلية", "توليد صورة فنية من وصف نصي."),
    "summarize": ("تلخيص (Summarize)", "أوامر الأعضاء — أدوات", "read_message_history", ["تلخيص"], "!summarize [العدد]", "!summarize 30", "تحليل آخر رسائل القناة وتلخيصها في نقاط."),
    # إدارة القنوات
    "setup_tickets": ("تهيئة التذاكر (Setup Tickets)", "إدارة القنوات", "manage_channels", ["تذاكر"], "!setup_tickets", "!setup_tickets", "تثبيت لوحة تذاكر الدعم الفني وإعداد قنواتها."),
    "ticket_reply": ("رد التذكرة (Ticket Reply)", "إدارة القنوات", "manage_channels", ["رد_تذكرة"], "!ticket_reply [النص]", "!ticket_reply أهلاً بك، نراجع طلبك الآن", "إرسال رد سريع ومنسق داخل التذكرة الحالية."),
    "ticket_close": ("إغلاق التذكرة (Ticket Close)", "إدارة القنوات", "manage_channels", ["إغلاق_تذكرة"], "!ticket_close [السبب]", "!ticket_close تم الحل", "إغلاق التذكرة وأرشفة محتواها وفق سياسة الدعم."),
    "ticket_transcript": ("سجل التذكرة (Ticket Transcript)", "إدارة القنوات", "manage_channels", ["نسخة_تذكرة"], "!ticket_transcript", "!ticket_transcript", "تصدير سجل التذكرة إلى أرشيف قابل للمراجعة."),
    "setup_roles": ("تهيئة الرتب (Setup Roles)", "إدارة القنوات", "manage_roles", ["رتب"], "!setup_roles", "!setup_roles", "تثبيت لوحة الرتب التفاعلية للأعضاء."),
    "setup_rules": ("تهيئة القوانين (Setup Rules)", "إدارة القنوات", "manage_channels", ["قوانين_تثبيت"], "!setup_rules", "!setup_rules", "تثبيت بوابة الموافقة على القوانين في القناة المحددة."),
    "setup_counters": ("عدادات السيرفر (Setup Counters)", "إدارة القنوات", "manage_channels", ["عدادات"], "!setup_counters", "!setup_counters", "تثبيت قنوات صوتية تعرض إحصائيات السيرفر الحية."),
    "setup_voice": ("الرومات المؤقتة (Setup Voice)", "إدارة القنوات", "administrator", ["رومات"], "!setup_voice", "!setup_voice", "تهيئة نظام رومات صوتية مؤقتة ذاتية الإدارة."),
    # أوامر متقدمة
    "transcript": ("أرشيف الرسائل (Transcript)", "أوامر متقدمة", "manage_messages", ["أرشفة"], "!transcript [العدد]", "!transcript 100", "تصدير رسائل القناة إلى ملف أرشيف نصي."),
    "backup_structure": ("نسخة الهيكل (Backup Structure)", "أوامر متقدمة", "administrator", ["نسخة_احتياطية"], "!backup_structure", "!backup_structure", "أخذ نسخة احتياطية من هيكل السيرفر ورتبه وإعداداته."),
    "backup_restore": ("استعادة الهيكل (Backup Restore)", "أوامر متقدمة", "administrator", ["استعادة"], "!backup_restore [المعرف]", "!backup_restore latest", "استعادة هيكل محفوظ بعد التأكيد والتحقق من صلاحيات المدير."),
    "imagine": ("توليد صورة (Imagine)", "أوامر متقدمة", "send_messages", ["صورة_ai"], "!imagine [الوصف]", "!imagine شعار أزرق مستقبلي", "توليد صورة فنية رقمية من وصف المستخدم."),
    "scrim_open": ("فتح السكريم (Scrim Open)", "أوامر متقدمة", "manage_events", ["سكريم"], "!scrim_open [العنوان] [اللعبة]", "!scrim_open بطولة Valorant", "فتح لوحة تسجيل سكريم للفرق وإدارة المقاعد."),
    "scrim_close": ("إغلاق السكريم (Scrim Close)", "أوامر متقدمة", "manage_events", ["إغلاق_سكريم"], "!scrim_close", "!scrim_close", "إغلاق تسجيل السكريم الحالي ومنع المشاركات الجديدة."),
    "scrim_split": ("تقسيم السكريم (Scrim Split)", "أوامر متقدمة", "move_members", ["تقسيم"], "!scrim_split [عدد الفرق]", "!scrim_split 2", "توزيع لاعبي الروم الصوتي بالتساوي بين الفرق."),
    "scrim_teams": ("فرق السكريم (Scrim Teams)", "أوامر متقدمة", "move_members", ["فرق"], "!scrim_teams [النمط]", "!scrim_teams squad", "تقسيم لاعبي الروم إلى فرق بالنمط المحدد."),
    "map_randomizer": ("اختيار الخريطة (Map Randomizer)", "أوامر متقدمة", "send_messages", ["خريطة"], "!map_randomizer [القائمة]", "!map_randomizer ranked", "اختيار خريطة عشوائية لمباراة تكتيكية."),
    "tournament_open": ("فتح البطولة (Tournament Open)", "أوامر متقدمة", "manage_events", ["بطولة"], "!tournament_open [العنوان]", "!tournament_open PRIME CUP", "فتح التسجيل لبطولة رسمية وتوليد جدولها."),
    "tournament_close": ("إغلاق البطولة (Tournament Close)", "أوامر متقدمة", "manage_events", ["إغلاق_بطولة"], "!tournament_close", "!tournament_close", "إغلاق التسجيل في البطولة الحالية."),
    "match_record": ("تسجيل المباراة (Match Record)", "أوامر متقدمة", "manage_events", ["نتيجة"], "!match_record [الفائز] [النتيجة]", "!match_record TeamA 2-1", "توثيق نتيجة مباراة وتوزيع نقاط الفوز."),
    "standings": ("ترتيب البطولة (Standings)", "أوامر متقدمة", "send_messages", ["ترتيب"], "!standings", "!standings", "عرض ترتيب فرق البطولات المحفوظ."),
    "set_leaderboard_channel": ("قناة المتصدرين (Leaderboard Channel)", "أوامر متقدمة", "manage_channels", ["قناة_المتصدرين"], "!set_leaderboard_channel [القناة]", "!set_leaderboard_channel #المتصدرين", "تثبيت لوحة المتصدرين الحية في قناة محددة."),
    "give_points": ("إضافة نقاط (Give Points)", "أوامر متقدمة", "administrator", ["نقاط"], "!give_points @عضو [العدد]", "!give_points @أحمد 100", "إضافة نقاط إلى محفظة عضو بصلاحية الإدارة."),
    "take_points": ("خصم نقاط (Take Points)", "أوامر متقدمة", "administrator", ["خصم_نقاط"], "!take_points @عضو [العدد]", "!take_points @أحمد 50", "خصم نقاط من محفظة عضو مع تسجيل العملية."),
    "give_level": ("ترقية مستوى (Give Level)", "أوامر متقدمة", "administrator", ["ترقية"], "!give_level @عضو [المستويات]", "!give_level @أحمد 2", "رفع مستوى عضو يدوياً بصلاحية الإدارة."),
    "take_level": ("تنزيل مستوى (Take Level)", "أوامر متقدمة", "administrator", ["تنزيل_مستوى"], "!take_level @عضو [المستويات]", "!take_level @أحمد 1", "خفض مستوى عضو يدوياً مع تسجيل التعديل."),
    "اعطاء_نقاط": ("إضافة نقاط عربية (Give Points)", "أوامر متقدمة", "administrator", ["give-points"], "!اعطاء_نقاط @عضو [العدد]", "!اعطاء_نقاط @أحمد 100", "اختصار عربي لإضافة نقاط إلى محفظة عضو."),
    "سحب_نقاط": ("سحب نقاط عربية (Take Points)", "أوامر متقدمة", "administrator", ["take-points"], "!سحب_نقاط @عضو [العدد]", "!سحب_نقاط @أحمد 50", "اختصار عربي لخصم نقاط من محفظة عضو."),
    "ترقية_مستوى": ("ترقية عربية (Give Level)", "أوامر متقدمة", "administrator", ["give-level"], "!ترقية_مستوى @عضو [المستويات]", "!ترقية_مستوى @أحمد 1", "اختصار عربي لترقية مستوى عضو."),
    "تنزيل_مستوى": ("تنزيل عربية (Take Level)", "أوامر متقدمة", "administrator", ["take-level"], "!تنزيل_مستوى @عضو [المستويات]", "!تنزيل_مستوى @أحمد 1", "اختصار عربي لتنزيل مستوى عضو."),
    "radio": ("الراديو (Radio)", "أوامر متقدمة", "connect", ["إذاعة"], "!radio", "!radio", "تشغيل إذاعة القرآن المباشرة في الروم الصوتي."),
    # السجل والملاحظات
    "snipe": ("آخر رسالة محذوفة (Snipe)", "السجل والملاحظات", "manage_messages", ["سناب"], "!snipe", "!snipe", "عرض آخر رسالة حُذفت من القناة إن كانت محفوظة."),
    "editsnipe": ("آخر تعديل (Edit Snipe)", "السجل والملاحظات", "manage_messages", ["تعديل"], "!editsnipe", "!editsnipe", "عرض آخر رسالة تم تعديلها مع النص السابق والجديد."),
    "history": ("سجل العضو (History)", "السجل والملاحظات", "view_audit_log", ["تاريخ"], "!history @عضو", "!history @أحمد", "عرض التاريخ الإداري والإنذارات المسجلة لعضو."),
    "suggest": ("اقتراح (Suggest)", "السجل والملاحظات", "send_messages", ["اقتراح"], "!suggest [النص]", "!suggest إضافة قناة للألعاب", "إرسال اقتراح وطرحه للتصويت والإدارة."),
    "transcript_log": ("سجل المحادثة (Transcript Log)", "السجل والملاحظات", "read_message_history", ["سجل_المحادثة"], "!transcript_log [العدد]", "!transcript_log 50", "عرض سجل مختصر لرسائل القناة للمراجعة."),
    "reminders_log": ("سجل التذكيرات (Reminders Log)", "السجل والملاحظات", "manage_messages", ["سجل_التذكيرات"], "!reminders_log", "!reminders_log", "عرض عمليات إنشاء وإلغاء التذكيرات في السيرفر."),
    # إحصائيات وتراجع
    "leaderboard": ("المتصدرون (Leaderboard)", "إحصائيات وتراجع", "send_messages", ["ترتيب_الأعضاء"], "!leaderboard [النوع]", "!leaderboard levels", "عرض إحصائيات المتصدرين وترتيب أعضاء السيرفر."),
    "stats": ("إحصائيات (Stats)", "إحصائيات وتراجع", "send_messages", ["إحصائيات"], "!stats [الفترة]", "!stats week", "عرض إحصائيات النشاط والأعضاء خلال فترة محددة."),
    "analytics": ("تحليل النشاط (Analytics)", "إحصائيات وتراجع", "view_audit_log", ["تحليل"], "!analytics [الفترة]", "!analytics month", "تحليل اتجاهات النشاط والتفاعل في السيرفر."),
    "rollback": ("تراجع آمن (Rollback)", "إحصائيات وتراجع", "administrator", ["تراجع"], "!rollback [المعرف]", "!rollback last", "التراجع عن إعداد مدعوم بعد تأكيد المدير وحفظ سجل العملية."),
    "giveaway_end": ("إنهاء السحب (Giveaway End)", "إحصائيات وتراجع", "manage_events", ["إنهاء_السحب"], "!giveaway_end [المعرف]", "!giveaway_end 12", "إنهاء سحب قائم واختيار الفائزين وفق الحالة الحالية."),
    "giveaway_reroll": ("إعادة السحب (Giveaway Reroll)", "إحصائيات وتراجع", "manage_events", ["إعادة_السحب"], "!giveaway_reroll [المعرف]", "!giveaway_reroll 12", "اختيار فائز بديل لسحب منتهٍ عند الحاجة."),
}

# Keep the public mapping stable and include the key in every metadata object.
MASTER_COMMANDS_REGISTRY = {
    key: _command(key, *spec)
    for key, spec in _COMMAND_SPECS.items()
}


def grouped_command_registry() -> list[dict]:
    """Return a JSON-ready, category-ordered copy for the dashboard API."""
    grouped = {category: [] for category in COMMAND_CATEGORIES}
    for metadata in MASTER_COMMANDS_REGISTRY.values():
        grouped.setdefault(metadata["category"], []).append(deepcopy(metadata))
    return [
        {
            "category": category,
            "commands": sorted(
                grouped[category],
                key=lambda item: (item["display_name"], item["key"]),
            ),
        }
        for category in COMMAND_CATEGORIES
        if grouped[category]
    ]


def command_metadata(command_name: str) -> dict | None:
    """Return a defensive copy so request handlers cannot mutate the registry."""
    item = MASTER_COMMANDS_REGISTRY.get(str(command_name).strip().lower())
    return deepcopy(item) if item else None