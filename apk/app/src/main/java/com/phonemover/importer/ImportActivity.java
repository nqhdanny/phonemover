package com.phonemover.importer;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.TextUtils;

import java.io.File;

/**
 * Invisible launcher/entry activity.
 *
 * <p>Android 12+ blocks manifest receivers from receiving broadcasts that are
 * treated as "background execution" (see "Background execution not allowed"
 * in the broadcast history), which is exactly how the HUAWEI host triggers the
 * import via {@code am broadcast}. A foreground Activity is NOT subject to that
 * restriction, so we route the import through here instead:
 *
 * <pre>
 *   adb shell am start -n com.phonemover.importer/.ImportActivity \
 *       --es type calendar --es path /sdcard/PhoneMover/calendar.ics
 * </pre>
 *
 * <p>The Activity has Theme.NoDisplay and finishes immediately, so the user
 * never sees it. It also serves as the launcher entry that takes the app out
 * of the "stopped" state after install.
 */
public final class ImportActivity extends Activity {

    private static final String IMPORT_DIR = "/sdcard/PhoneMover";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        String type = intent != null ? intent.getStringExtra("type") : null;
        String path = intent != null ? intent.getStringExtra("path") : null;

        if (!TextUtils.isEmpty(type)) {
            if (TextUtils.isEmpty(path)) {
                if ("calendar".equals(type)) {
                    path = IMPORT_DIR + "/calendar.ics";
                } else if ("reminders".equals(type)) {
                    path = IMPORT_DIR + "/reminders.ics";
                } else {
                    path = IMPORT_DIR + "/contacts.vcf";
                }
            }
            // The actual import logic lives in ImportReceiver (shared helpers).
            ImportReceiver.run(this, type, path);
        }

        finish();
    }
}
