package jp.local.pachiboledger;

import java.math.BigInteger;

/** Positive user input with an explicit direction; no signed keyboard entry required. */
final class AmountInput {
    static long signed(String text,boolean expense) {
        String value=normalize(text);
        if(!value.matches("[0-9]+")) throw new IllegalArgumentException("金額・数量を0以上の整数で入力してください（ゼロの場合は0）");
        BigInteger result=new BigInteger(value);
        if(expense) result=result.negate();
        if(result.compareTo(BigInteger.valueOf(Long.MIN_VALUE))<0 || result.compareTo(BigInteger.valueOf(Long.MAX_VALUE))>0)
            throw new IllegalArgumentException("入力できる金額・数量の範囲を超えています");
        return result.longValue();
    }
    static String normalize(String text) {
        return java.text.Normalizer.normalize(text,java.text.Normalizer.Form.NFKC).replace(",","").replaceAll("\\s+","");
    }
}
