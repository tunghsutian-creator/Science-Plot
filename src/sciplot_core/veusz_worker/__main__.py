from sciplot_core.veusz_worker import main
from sciplot_core.veusz_worker.categorical_rejection import categorical_rejection_frame

with categorical_rejection_frame():
    raise SystemExit(main())
