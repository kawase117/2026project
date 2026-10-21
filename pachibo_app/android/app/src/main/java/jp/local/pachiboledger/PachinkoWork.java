package jp.local.pachiboledger;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Four-yen pachinko, with both rates expressed as normal spins per 250 balls. */
final class PachinkoWork {
    private static final BigDecimal BALLS=new BigDecimal("250"), FOUR=new BigDecimal("4");
    private static final int SCALE=16;
    private PachinkoWork() {}

    static BigDecimal unit(BigDecimal equalBorder,BigDecimal rotationRate,BigDecimal holdingPercent,
                           long exchangeYen,long exchangeBalls) {
        if(equalBorder==null||rotationRate==null||holdingPercent==null||equalBorder.signum()<=0||
            rotationRate.signum()<=0||holdingPercent.signum()<0||holdingPercent.compareTo(new BigDecimal("100"))>0)
            throw new IllegalArgumentException("等価ボーダー・回転率は正数、持ち玉比率は0～100%で入力してください");
        if(exchangeYen<=0||exchangeBalls<=0)throw new IllegalArgumentException("4円パチンコの交換率を登録してください");
        BigDecimal exchange=BigDecimal.valueOf(exchangeYen).divide(BigDecimal.valueOf(exchangeBalls),SCALE,RoundingMode.HALF_UP);
        if(exchange.compareTo(FOUR)>0)throw new IllegalArgumentException("4円パチンコの交換率は1玉4円以下にしてください");
        BigDecimal inverseBorder=BigDecimal.ONE.divide(equalBorder,SCALE,RoundingMode.HALF_UP);
        BigDecimal inverseRate=BigDecimal.ONE.divide(rotationRate,SCALE,RoundingMode.HALF_UP);
        BigDecimal holding=holdingPercent.divide(new BigDecimal("100"),SCALE,RoundingMode.HALF_UP);
        return inverseBorder.subtract(inverseRate).multiply(BALLS).multiply(exchange)
            .subtract(BigDecimal.ONE.subtract(holding).multiply(inverseRate).multiply(BALLS)
                .multiply(FOUR.subtract(exchange)));
    }

    static long workYen(BigDecimal unit,long normalSpins) {
        if(normalSpins<=0)throw new IllegalArgumentException("仕事量の計算には通常回転数を入力してください");
        try{return unit.multiply(BigDecimal.valueOf(normalSpins)).setScale(0,RoundingMode.HALF_UP).longValueExact();}
        catch(ArithmeticException error){throw new IllegalArgumentException("計算した仕事量が大きすぎます");}
    }

    static BigDecimal parse(String input,String name) {
        String normalized=java.text.Normalizer.normalize(input.trim(),java.text.Normalizer.Form.NFKC)
            .replace(",","").replace(" ","");
        try{return new BigDecimal(normalized);}
        catch(NumberFormatException error){throw new IllegalArgumentException(name+"は数字で入力してください");}
    }
}
