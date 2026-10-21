package jp.local.pachiboledger;

import android.content.Context;
import android.content.SharedPreferences;

/** Preferences affect presentation only; hiding a field never deletes saved values. */
final class EntryPreferences {
    private EntryPreferences() {}
    private static SharedPreferences settings(Context context){
        return context.getSharedPreferences("entry_fields",Context.MODE_PRIVATE);
    }
    static boolean number(Context context){return settings(context).getBoolean("number",true);}
    static boolean time(Context context){return settings(context).getBoolean("time",true);}
    static boolean advanced(Context context){return settings(context).getBoolean("advanced",false);}
    static void set(Context context,String key,boolean value){settings(context).edit().putBoolean(key,value).apply();}
}
