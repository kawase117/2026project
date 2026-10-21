package jp.local.pachiboledger;

import java.math.BigInteger;
import java.util.*;

/** Exact accounting only. Callers select completed, reviewed sessions of one accounting basis. */
public final class Accounting {
    private Accounting() {}

    public static final class Amount {
        public final BigInteger numerator, denominator;
        public Amount(long numerator, long denominator) {
            this(BigInteger.valueOf(numerator), BigInteger.valueOf(denominator));
        }
        private Amount(BigInteger n, BigInteger d) {
            if (d.signum() <= 0) throw new IllegalArgumentException("Positive denominator required");
            BigInteger gcd = n.gcd(d);
            numerator = n.divide(gcd);
            denominator = d.divide(gcd);
        }
        public Amount add(Amount other) {
            return new Amount(numerator.multiply(other.denominator).add(other.numerator.multiply(denominator)),
                denominator.multiply(other.denominator));
        }
        public Amount multiply(long value) {
            return new Amount(numerator.multiply(BigInteger.valueOf(value)), denominator);
        }
        public BigInteger roundYen() {
            BigInteger[] parts = numerator.abs().divideAndRemainder(denominator);
            if (parts[1].shiftLeft(1).compareTo(denominator) >= 0) parts[0] = parts[0].add(BigInteger.ONE);
            return numerator.signum() < 0 ? parts[0].negate() : parts[0];
        }
    }

    public static final class Rate {
        public final Amount yenPerUnit;
        public Rate(long yen, long units) {
            if (yen <= 0 || units <= 0) throw new IllegalArgumentException("Positive rate required");
            yenPerUnit = new Amount(yen, units);
        }
    }

    /** Signed cash or stored/carry quantity. Exchange quantities are metadata, not a second entry. */
    public static final class Entry {
        public final String id, sessionId;
        public final long delta;
        public final boolean isCash;
        public final Rate rate;
        private Entry(String id, String sessionId, long delta, boolean cash, Rate rate) {
            this.id = required(id); this.sessionId = required(sessionId);
            this.delta = delta; this.isCash = cash; this.rate = rate;
        }
        public static Entry cash(String id, String session, long yen) {
            return new Entry(id, session, yen, true, null);
        }
        public static Entry quantity(String id, String session, long units, Rate rate) {
            return new Entry(id, session, units, false, rate);
        }
    }

    /** One shared valuation snapshot for both endpoints; null quantity/rate means unknown. */
    public static final class Transfer {
        public final String id, from, to;
        public final Long quantity;
        public final Rate rate;
        public Transfer(String id, String from, String to, Long quantity, Rate rate) {
            this.id = required(id); this.from = required(from); this.to = required(to);
            if (from.equals(to) || (quantity != null && quantity < 0))
                throw new IllegalArgumentException("Invalid transfer");
            this.quantity = quantity; this.rate = rate;
        }
    }

    public static final class Result {
        public final BigInteger cash;
        /** Null when no observations or an unresolved external quantity prevents evaluation. */
        public final Amount evaluated;
        public final Set<String> unresolvedIds;
        public final boolean hasObservations;
        private Result(BigInteger cash, Amount evaluated, Set<String> unresolved, boolean observed) {
            this.cash = cash; this.evaluated = evaluated;
            this.unresolvedIds = Collections.unmodifiableSet(new LinkedHashSet<>(unresolved));
            this.hasObservations = observed;
        }
    }

    /** Pass all relevant transfers, including those crossing the selection boundary. */
    public static Result calculate(Collection<Entry> entries, Collection<Transfer> transfers, Set<String> selected) {
        Objects.requireNonNull(selected);
        BigInteger cash = BigInteger.ZERO;
        Amount total = new Amount(0, 1);
        Set<String> ids = new HashSet<>(), unresolved = new LinkedHashSet<>();
        boolean observed = false;
        for (Entry e : entries) {
            if (!ids.add(e.id)) throw new IllegalArgumentException("Duplicate operation: " + e.id);
            if (!selected.contains(e.sessionId)) continue;
            observed = true;
            if (e.isCash) {
                cash = cash.add(BigInteger.valueOf(e.delta));
                total = total.add(new Amount(e.delta, 1));
            } else if (e.delta != 0) {
                if (e.rate == null) unresolved.add(e.id);
                else total = total.add(e.rate.yenPerUnit.multiply(e.delta));
            }
        }
        for (Transfer t : transfers) {
            if (!ids.add(t.id)) throw new IllegalArgumentException("Duplicate operation: " + t.id);
            boolean from = selected.contains(t.from), to = selected.contains(t.to);
            if (!from && !to) continue;
            observed = true;
            // Internal flows cancel even when the transferred quantity is unknown.
            if (from && to) continue;
            if (t.quantity != null && t.quantity == 0) continue;
            if (t.quantity == null || t.rate == null) unresolved.add(t.id);
            else total = total.add(t.rate.yenPerUnit.multiply(from ? t.quantity : -t.quantity));
        }
        return new Result(cash, observed && unresolved.isEmpty() ? total : null, unresolved, observed);
    }

    private static String required(String value) {
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException("ID required");
        return value;
    }
}
