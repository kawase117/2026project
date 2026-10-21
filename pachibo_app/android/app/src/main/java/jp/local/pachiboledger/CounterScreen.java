package jp.local.pachiboledger;

import android.app.Activity;
import android.app.AlertDialog;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;

final class CounterScreen {
    private CounterScreen(){}
    static void show(Activity activity,LedgerDb db,String type,String ownerId){
        CounterStore store=new CounterStore(db);
        LinearLayout panel=new LinearLayout(activity);panel.setOrientation(1);panel.setPadding(20,12,20,12);
        ScrollView scroll=new ScrollView(activity);scroll.addView(panel);
        AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("小役カウンタ")
            .setView(scroll).setPositiveButton("閉じる",null).create();
        Runnable[] render=new Runnable[1];
        render[0]=()->{
            panel.removeAllViews();
            TextView guidance=new TextView(activity);guidance.setText("加算は自動保存されます。『直前を取消』はその項目の直前の加算を1回だけ戻します。");
            panel.addView(guidance);
            Button add=new Button(activity);add.setText("項目を追加");panel.addView(add);
            add.setOnClickListener(v->{
                EditText input=new EditText(activity);input.setSingleLine(true);input.setHint("例：ベル、チェリー");
                new AlertDialog.Builder(activity).setTitle("項目名").setView(input).setNegativeButton("戻る",null)
                    .setPositiveButton("追加",(d,w)->attempt(activity,()->{store.add(type,ownerId,input.getText().toString());render[0].run();})).show();
            });
            try{
                JSONArray rows=store.list(type,ownerId);
                for(int i=0;i<rows.length();i++){
                    JSONObject row=rows.getJSONObject(i);String id=row.getString("id");
                    LinearLayout line=new LinearLayout(activity);line.setOrientation(LinearLayout.HORIZONTAL);panel.addView(line);
                    Button plus=new Button(activity);FormUi.styleButton(plus);
                    plus.setText(row.getString("name")+"  "+row.getLong("count")+"  ＋1");
                    line.addView(plus,new LinearLayout.LayoutParams(0,-2,1));
                    plus.setOnClickListener(v->attempt(activity,()->{store.increment(id);render[0].run();}));
                    Button undo=new Button(activity);FormUi.styleButton(undo);undo.setText("取消");
                    undo.setEnabled(row.optBoolean("undo_available"));line.addView(undo);
                    undo.setOnClickListener(v->attempt(activity,()->{store.undo(id);render[0].run();}));
                }
            }catch(Exception e){error(activity,e);}
        };
        render[0].run();dialog.show();
    }
    private interface Action{void run()throws Exception;}
    private static void attempt(Activity activity,Action action){try{action.run();}catch(Exception e){error(activity,e);}}
    private static void error(Activity activity,Exception e){new AlertDialog.Builder(activity)
        .setTitle("カウンタを更新できません").setMessage(e.getMessage()).setPositiveButton("閉じる",null).show();}
}
