# Run inside the offline Coq task image with the submitted files mounted read-only at /submission.
set -eu
export LC_ALL=C
work=$(mktemp -d)
cd "$work"
cat > Audit.v <<'EOF'
Require Import plus_comm.
Definition checked : forall n m : nat, n + m = m + n := plus_comm.plus_comm.
Print Assumptions checked.
EOF
coqc --version
for phase in submitted_object rebuilt_source; do
    mkdir "$phase"
    cp Audit.v "$phase/"
    (
        cd "$phase"
        if [ "$phase" = submitted_object ]; then
            cp /submission/plus_comm.vo .
        else
            cp /submission/plus_comm.v .
            coqc plus_comm.v
        fi
        coqchk -silent plus_comm
        coqc Audit.v > assumptions.txt
        cat assumptions.txt
        grep -Fxq 'Closed under the global context' assumptions.txt
        echo "$phase passed type, kernel and assumptions checks"
    )
done
