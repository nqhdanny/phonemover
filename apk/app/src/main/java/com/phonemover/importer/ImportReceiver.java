package com.phonemover.importer;

import android.content.BroadcastReceiver;
import android.content.ContentProviderOperation;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.provider.CalendarContract;
import android.provider.ContactsContract;
import android.text.TextUtils;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

/**
 * ImportReceiver — performs the actual data import on the HUAWEI device.
 *
 * <p>The Windows host pushes {@code contacts.vcf} / {@code calendar.ics} to
 * {@code /sdcard/PhoneMover/} via {@code adb push}, then fires:
 *
 * <pre>
 *   adb shell am broadcast -a com.phonemover.importer.IMPORT \
 *       --es type contacts --es path /sdcard/PhoneMover/contacts.vcf
 * </pre>
 *
 * <p>This receiver parses the file and inserts rows through the system
 * ContentResolver (Contacts / Calendar providers). All work is synchronous —
 * the host waits for the broadcast result via {@code am broadcast}.
 */
public final class ImportReceiver extends BroadcastReceiver {

    public static final String ACTION_IMPORT = "com.phonemover.importer.IMPORT";
    public static final String EXTRA_TYPE = "type";   // "contacts" | "calendar"
    public static final String EXTRA_PATH = "path";   // absolute file path

    private static final String IMPORT_DIR = "/sdcard/PhoneMover";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_IMPORT.equals(intent.getAction())) {
            return;
        }
        String type = intent.getStringExtra(EXTRA_TYPE);
        String path = intent.getStringExtra(EXTRA_PATH);
        if (TextUtils.isEmpty(type)) {
            type = "contacts";
        }
        if (TextUtils.isEmpty(path)) {
            if ("calendar".equals(type)) {
                path = IMPORT_DIR + "/calendar.ics";
            } else if ("reminders".equals(type)) {
                path = IMPORT_DIR + "/reminders.ics";
            } else {
                path = IMPORT_DIR + "/contacts.vcf";
            }
        }

        int count;
        if ("scan".equals(type)) {
            // Media rescan: index a directory so the Gallery/Music apps see
            // files pushed via adb. Returns the number of files scanned.
            count = scanMedia(context, new File(path));
            writeResult(type, count);
            return;
        } else if ("calendar".equals(type)) {
            count = importCalendar(context, new File(path));
        } else if ("reminders".equals(type)) {
            count = importReminders(context, new File(path));
        } else {
            count = importContacts(context, new File(path));
        }

        // `am broadcast` sends a NON-ordered broadcast, so setResultData() /
        // setResult() have no effect and their value never reaches the host.
        // Instead we write the count to a result file on /sdcard, which the
        // host reads back via `adb shell cat`.
        writeResult(type, count);
    }

    /**
     * Write the import count to /sdcard/PhoneMover/result_<type>.txt so the
     * host can read it back (the broadcast result channel is unavailable for
     * non-ordered broadcasts).
     */
    private void writeResult(String type, int count) {
        File dir = new File(IMPORT_DIR);
        if (!dir.exists()) {
            dir.mkdirs();
        }
        File out = new File(dir, "result_" + type + ".txt");
        try {
            java.io.FileWriter w = new java.io.FileWriter(out);
            w.write(String.valueOf(count));
            w.close();
        } catch (Exception ignored) {
            // Best effort: if we can't write the result file, the host will
            // report 0, but the actual import may still have succeeded.
        }
    }

    // -- Media scan -------------------------------------------------------

    /**
     * Index every file under {@code dir} into the MediaStore so the Gallery /
     * Music apps display files that were pushed via adb.
     *
     * <p>adb push writes files directly and does not trigger a media scan, so
     * without this the files exist on disk but are invisible in the gallery.
     * We use MediaScannerConnection.scanFile() (the public API) over the whole
     * directory, which is reliable on HUAWEI/EMUI.
     */
    private int scanMedia(Context context, File dir) {
        if (dir == null || !dir.exists() || !dir.isDirectory()) {
            return -1;
        }
        File[] children = dir.listFiles();
        if (children == null) {
            return 0;
        }
        String[] paths = new String[children.length];
        for (int i = 0; i < children.length; i++) {
            paths[i] = children[i].getAbsolutePath();
        }

        // MediaScannerConnection.scanFile() is asynchronous: it schedules the
        // scan on a background thread and returns immediately. The gallery will
        // show the files once scanning completes (usually within seconds). We
        // report the file count immediately; the actual indexing finishes in
        // the background.
        android.media.MediaScannerConnection.scanFile(
                context,
                paths,
                null,
                new android.media.MediaScannerConnection.OnScanCompletedListener() {
                    @Override
                    public void onScanCompleted(String path, android.net.Uri uri) {
                        // No-op: the scan result is reflected in the gallery.
                    }
                });
        return paths.length;
    }

    // -- Contacts ---------------------------------------------------------

    private int importContacts(Context context, File file) {
        if (!file.exists()) {
            return -1;
        }
        String vcf = readFile(file);
        if (vcf == null) {
            return -1;
        }

        // Split vCards on the BEGIN:VCARD marker (blank-line separated).
        String[] cards = vcf.split("END:VCARD");
        ContentResolver resolver = context.getContentResolver();
        ArrayList<ContentProviderOperation> ops = new ArrayList<>();
        int count = 0;

        for (String card : cards) {
            if (card == null || !card.contains("FN:")) {
                continue;
            }
            ops.clear();
            ops.add(ContentProviderOperation
                    .newInsert(ContactsContract.RawContacts.CONTENT_URI)
                    .withValue(ContactsContract.RawContacts.ACCOUNT_TYPE, null)
                    .withValue(ContactsContract.RawContacts.ACCOUNT_NAME, null)
                    .build());

            String fullName = extractField(card, "FN:");
            String givenName = "";
            String familyName = "";
            int nameIdx = card.indexOf("N:");
            if (nameIdx >= 0) {
                String nLine = card.substring(nameIdx + 2);
                int nl = nLine.indexOf('\n');
                if (nl >= 0) {
                    nLine = nLine.substring(0, nl);
                }
                String[] parts = nLine.split(";");
                familyName = parts.length > 0 ? parts[0] : "";
                givenName = parts.length > 1 ? parts[1] : "";
            }

            int nameInsertIdx = ops.size();
            ops.add(ContentProviderOperation
                    .newInsert(ContactsContract.Data.CONTENT_URI)
                    .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                    .withValue(ContactsContract.Data.MIMETYPE,
                            ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE)
                    .withValue(ContactsContract.CommonDataKinds.StructuredName.DISPLAY_NAME, fullName)
                    .withValue(ContactsContract.CommonDataKinds.StructuredName.GIVEN_NAME, givenName)
                    .withValue(ContactsContract.CommonDataKinds.StructuredName.FAMILY_NAME, familyName)
                    .build());

            for (String line : card.split("\n")) {
                line = line.trim();
                if (line.startsWith("TEL")) {
                    String number = valueAfterColon(line);
                    if (!TextUtils.isEmpty(number)) {
                        ops.add(ContentProviderOperation
                                .newInsert(ContactsContract.Data.CONTENT_URI)
                                .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                                .withValue(ContactsContract.Data.MIMETYPE,
                                        ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE)
                                .withValue(ContactsContract.CommonDataKinds.Phone.NUMBER, number)
                                .withValue(ContactsContract.CommonDataKinds.Phone.TYPE,
                                        ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE)
                                .build());
                    }
                } else if (line.startsWith("EMAIL")) {
                    String email = valueAfterColon(line);
                    if (!TextUtils.isEmpty(email)) {
                        ops.add(ContentProviderOperation
                                .newInsert(ContactsContract.Data.CONTENT_URI)
                                .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                                .withValue(ContactsContract.Data.MIMETYPE,
                                        ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE)
                                .withValue(ContactsContract.CommonDataKinds.Email.ADDRESS, email)
                                .withValue(ContactsContract.CommonDataKinds.Email.TYPE,
                                        ContactsContract.CommonDataKinds.Email.TYPE_HOME)
                                .build());
                    }
                }
            }

            try {
                resolver.applyBatch(ContactsContract.AUTHORITY, ops);
                count++;
            } catch (Exception ignored) {
                // Skip malformed cards; continue with the rest.
            }
        }
        return count;
    }

    // -- Calendar ---------------------------------------------------------

    private int importCalendar(Context context, File file) {
        if (!file.exists()) {
            return -1;
        }
        String ics = readFile(file);
        if (ics == null) {
            return -1;
        }

        ContentResolver resolver = context.getContentResolver();
        String[] events = ics.split("END:VEVENT");
        int count = 0;

        for (String event : events) {
            if (event == null || !event.contains("SUMMARY")) {
                continue;
            }
            String summary = extractField(event, "SUMMARY:");
            long start = parseIcsDate(event, "DTSTART");
            if (start <= 0) {
                continue;
            }
            long end = parseIcsDate(event, "DTEND");
            if (end <= start) {
                end = start + 3600_000L; // default 1h
            }
            String location = extractField(event, "LOCATION:");
            String description = extractField(event, "DESCRIPTION:");
            boolean allDay = event.contains("DTSTART;VALUE=DATE");

            ContentValues values = new ContentValues();
            values.put(CalendarContract.Events.CALENDAR_ID, defaultCalendarId(context));
            values.put(CalendarContract.Events.TITLE, summary);
            values.put(CalendarContract.Events.DTSTART, start);
            values.put(CalendarContract.Events.DTEND, end);
            if (!TextUtils.isEmpty(location)) {
                values.put(CalendarContract.Events.EVENT_LOCATION, location);
            }
            if (!TextUtils.isEmpty(description)) {
                values.put(CalendarContract.Events.DESCRIPTION, description);
            }
            values.put(CalendarContract.Events.EVENT_TIMEZONE, "UTC");
            values.put(CalendarContract.Events.ALL_DAY, allDay ? 1 : 0);

            try {
                Uri uri = resolver.insert(CalendarContract.Events.CONTENT_URI, values);
                if (uri != null) {
                    count++;
                }
            } catch (Exception ignored) {
                // Requires calendar write permission; skip if denied.
            }
        }
        return count;
    }

    // -- Reminders --------------------------------------------------------

    /**
     * Import reminders from an .ics file containing VTODO entries.
     *
     * <p>The HUAWEI device has no public Reminders provider, so we convert
     * each VTODO into a calendar event on the DUE date (or creation date if
     * no due date). The original reminder title/notes are preserved as the
     * event title/description, prefixed with "[Reminder]".
     */
    private int importReminders(Context context, File file) {
        if (!file.exists()) {
            return -1;
        }
        String ics = readFile(file);
        if (ics == null) {
            return -1;
        }

        ContentResolver resolver = context.getContentResolver();
        String[] todos = ics.split("END:VTODO");
        int count = 0;

        for (String todo : todos) {
            if (todo == null || !todo.contains("SUMMARY")) {
                continue;
            }
            String summary = extractField(todo, "SUMMARY:");
            if (TextUtils.isEmpty(summary)) {
                continue;
            }
            String notes = extractField(todo, "DESCRIPTION:");

            // Use DUE date if present, otherwise CREATED, otherwise now.
            long due = parseIcsDate(todo, "DUE");
            if (due <= 0) {
                due = parseIcsDate(todo, "CREATED");
            }
            if (due <= 0) {
                due = System.currentTimeMillis();
            }
            long end = due + 3600_000L; // 1h block

            ContentValues values = new ContentValues();
            values.put(CalendarContract.Events.CALENDAR_ID, defaultCalendarId(context));
            values.put(CalendarContract.Events.TITLE, "[Reminder] " + summary);
            values.put(CalendarContract.Events.DTSTART, due);
            values.put(CalendarContract.Events.DTEND, end);
            if (!TextUtils.isEmpty(notes)) {
                values.put(CalendarContract.Events.DESCRIPTION, notes);
            }
            values.put(CalendarContract.Events.EVENT_TIMEZONE, "UTC");
            values.put(CalendarContract.Events.ALL_DAY, 0);

            try {
                Uri uri = resolver.insert(CalendarContract.Events.CONTENT_URI, values);
                if (uri != null) {
                    count++;
                }
            } catch (Exception ignored) {
                // skip on failure
            }
        }
        return count;
    }

    // -- Helpers ----------------------------------------------------------

    private long defaultCalendarId(Context context) {
        String[] projection = { CalendarContract.Calendars._ID };
        try {
            android.database.Cursor c = context.getContentResolver().query(
                    CalendarContract.Calendars.CONTENT_URI, projection, null, null, null);
            if (c != null) {
                try {
                    if (c.moveToFirst()) {
                        return c.getLong(0);
                    }
                } finally {
                    c.close();
                }
            }
        } catch (Exception ignored) {
            // no calendar access
        }
        return 1L; // fallback
    }

    private String readFile(File file) {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(file), StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append('\n');
            }
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    private String extractField(String block, String key) {
        int idx = block.indexOf(key);
        if (idx < 0) {
            return "";
        }
        String line = block.substring(idx + key.length());
        int nl = line.indexOf('\n');
        if (nl >= 0) {
            line = line.substring(0, nl);
        }
        return unescape(line.trim());
    }

    private String valueAfterColon(String line) {
        int idx = line.indexOf(':');
        if (idx < 0) {
            return "";
        }
        String v = line.substring(idx + 1).trim();
        // Strip vCard parameters like ";TYPE=CELL" (already handled by caller split).
        return v;
    }

    private String unescape(String s) {
        return s.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n").replace("\\\\", "\\");
    }

    private long parseIcsDate(String event, String key) {
        // Accept DTSTART:YYYYMMDDTHHMMSSZ or DTSTART;VALUE=DATE:YYYYMMDD
        String raw = extractField(event, key + ";VALUE=DATE:");
        if (TextUtils.isEmpty(raw)) {
            raw = extractField(event, key + ":");
        }
        if (TextUtils.isEmpty(raw)) {
            return -1;
        }
        try {
            if (raw.length() == 8) {
                // YYYYMMDD
                int y = Integer.parseInt(raw.substring(0, 4));
                int mo = Integer.parseInt(raw.substring(4, 6));
                int d = Integer.parseInt(raw.substring(6, 8));
                java.util.Calendar cal = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("UTC"));
                cal.clear();
                cal.set(y, mo - 1, d, 0, 0, 0);
                return cal.getTimeInMillis();
            }
            // YYYYMMDDTHHMMSSZ
            String y = raw.substring(0, 4);
            String mo = raw.substring(4, 6);
            String d = raw.substring(6, 8);
            String h = raw.length() >= 11 ? raw.substring(9, 11) : "00";
            String mi = raw.length() >= 13 ? raw.substring(11, 13) : "00";
            String s2 = raw.length() >= 15 ? raw.substring(13, 15) : "00";
            java.util.Calendar cal = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("UTC"));
            cal.clear();
            cal.set(Integer.parseInt(y), Integer.parseInt(mo) - 1, Integer.parseInt(d),
                    Integer.parseInt(h), Integer.parseInt(mi), Integer.parseInt(s2));
            return cal.getTimeInMillis();
        } catch (Exception e) {
            return -1;
        }
    }
}
