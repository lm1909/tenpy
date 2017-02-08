"""This module contains a base class for a Matrix Product State (MPS).

An MPS looks roughly like this::

    |   -- B[0] -- B[1] -- B[2] -- ...
    |       |       |      |

We use the following label convention for the `B` (where arrows indicate `qconj`)::

    |  vL ->- B ->- vR
    |         |
    |         ^
    |         p

We store one 3-leg tensor `_B[i]` with labels ``'vL', 'vR', 'p'`` for each of the `L` sites
``0 <= i < L``.
Additionally, we store ``L+1`` singular value arrays `_S[ib]` on each bond ``0 <= ib <= L``,
independent of the boundary conditions.
``_S[ib]`` gives the singlur values on the bond ``i-1, i``.
However, be aware that e.g. :attr:`MPS.chi` returns only the dimensions of the
:attr:`MPS.nontrivial_bonds` depending on the boundary conditions.

We restrict ourselves to normalized states (i.e. ``np.linalg.norm(psi._S[ib]) == 1`` up to
roundoff errors).

For efficient simulations, it is crucial that the MPS is in a 'canonical form'.
The different forms and boundary conditions are easiest described in Vidal's
:math:`\Gamma, \Lambda` notation [1]_.

Valid MPS boundary conditions (not to confuse with `bc_coupling` of
:class:`tenpy.models.model.CouplingModel`)  are the following:

==========  ===================================================================================
`bc`        description
==========  ===================================================================================
'finite'    Finite MPS, ``G0 s1 G1 ... s{L-1} G{l-1}``. This is acchieved
            by using a trivial left and right bond ``s[0] = s[-1] = np.array([1.])``.
'segment'   Generalization of 'finite', describes an MPS embedded in left and right
            environments. The left environment is described by ``chi[0]`` *orthonormal* states
            which are weighted by the singular values ``s[0]``. Similar, ``s[L]`` weight some
            right orthonormal states. You can think of the left and right states to be
            generated by additional MPS, such that the overall structure is something like
            ``... s L s L [s0 G0 s1 G1 ... s{L-1} G{L-1} s{L}] R s R s R ... ``
            (where we save the part in the brackets ``[ ... ]``).
'infinite'  infinite MPS (iMPS): we save a 'MPS unit cell' ``[s0 G0 s1 G1 ... s{L-1} G{L-1}]``
            which is repeated periodically, identifying all indices modulo ``self.L``.
            In particular, the last bond ``L`` is identified with ``0``.
            (The MPS unit cell can differ from a lattice unit cell).
            bond is identified with the first one.
==========  ===================================================================================

An MPS can be in different 'canonical forms' (see [1]_, [2]_).
To take care of the different canonical forms, algorithms should use functions like
:meth:`get_theta`, :meth:`get_B` and :meth:`set_B` instead of accessing them directly,
as they return the `B` in the desired form (which can be chosed as an argument).

======== ========== =======================================================================
`form`   tuple      description
======== ========== =======================================================================
``'B'``  (0, 1)     right canonical: ``_B[i] = -- Gamma[i] -- s[i+1]--``
                    The default form, which algorithms asssume.
``'C'``  (0.5, 0.5) symmetric form: ``_B[i] = -- s[i]**0.5 -- Gamma[i] -- s[i+1]**0.5--``
``'A'``  (1, 0)     left canonical: ``_B[i] = -- s[i] -- Gamma[i] --``.
                    For stability reasons, we recommend to *not* use this form.
``'G'``  (0, 0)     Save only ``_B[i] = -- Gamma[i] --``.
                    For stability reasons, we recommend to *not* use this form.
``None`` ``None``   General non-canoncial form.
                    Valid form for initialization, but you need to call
                    :meth:`canonicalize` (or sub-functions) before using algorithms.
======== ========== =======================================================================

.. todo ::

    - expectaion values
    - canonicalize()
    - much much more ....
    - proper documentation
    - copy

References
----------
.. [1] G. Vidal, Phys. Rev. Lett. 93, 040502 (2004), arXiv:quant-ph/0310089
.. [2] U. Schollwoeck, Annals of Physics 326, 96 (2011), arXiv:1008.3477
"""

from __future__ import division
import numpy as np

from ..linalg import np_conserved as npc
from ..tools.misc import to_iterable


class MPS(object):
    r"""A Matrix Product State, finite (MPS) or infinite (iMPS).

    Parameters
    ----------
    sites : list of :class:`~tenpy.networks.site.Site`
        Defines the local Hilbert space for each site.
    Bs : list of :class:`~tenpy.linalg.np_conserved.Array`
        The 'matrices' of the MPS. Labels are ``vL, vR, p`` (in any order).
    SVs : list of 1D array
        The singular values on *each* bond. Should always have length `L+1`.
        Entries out of :attr:`nontrivial_bonds` are ignored.
    bc : ``'finite' | 'segment' | 'infinite'``
        Boundary conditions as described in the tabel of the module doc-string.
    form : (list of) {``'B' | 'A' | 'C' | 'G' | None`` | tuple(float, float)}
        The form the stored 'matrices'. The table in module doc-string.
        A single choice holds for all of the entries.

    Attributes
    ----------
    L
    chi
    finite
    nontrivial_bonds
    sites : list of :class:`~tenpy.networks.site.Site`
        Defines the local Hilbert space for each site.
    bc : {'finite', 'segment', 'infinite'}
        Boundary conditions as described in above table.
    form : list of {``None`` | tuple(float, float)}
        Describes the canonical form on each site.
        ``None`` means non-canonical form.
        For ``form = (nuL, nuR)``, the stored ``_B[i]`` are
        ``s**form[0] -- Gamma -- s**form[1]`` (in Vidal's notation).
    dtype : type
        The data type of the `_B`.
    _B : list of :class:`npc.Array`
        The 'matrices' of the MPS. Labels are ``vL, vR, p`` (in any order).
        We recommend using :meth:`get_B` and :meth:`set_B`, which will take care of the different
        canonical forms.
    _S : None | list of 1D arrays
        The singular values on each virtual bond, length ``L+1``.
        May be ``None`` if the MPS is not in canonical form.
        Otherwise, ``_S[i]`` is to the left of ``_B[i]``.
        We recommend using :meth:`get_SL`, :meth:`get_SR`, :meth:`set_SL`, :meth:`set_SR`, which
        take proper care of the boundary conditions.
    _valid_forms : dict
        Mapping for canonical forms to a tuple ``(nuL, nuR)`` indicating that
        ``self._Bs[i] = s[i]**nuL -- Gamma[i] -- s[i]**nuR`` is saved.
    _valid_bc : tuple of str
        Valid boundary conditions.
    """

    # Canonical form conventions: the saved B = s**nu[0]--Gamma--s**nu[1].
    # For the canonical forms, ``nu[0] + nu[1] = 1``
    _valid_forms = {
        'A': (1., 0.),
        'C': (0.5, 0.5),
        'B': (0., 1.),
        'G': (0., 0.),  # like Vidal's `Gamma`.
        None: None,  # means 'not in any canonical form'
    }

    # valid boundary conditions. Don't overwrite this!
    _valid_bc = ('finite', 'segment', 'infinite')

    def __init__(self, sites, Bs, SVs, bc='finite', form='B'):
        self.sites = list(sites)
        self.chinfo = self.sites[0].leg.chinfo
        self.dtype = dtype = np.find_common_type([B.dtype for B in Bs], [])
        self.form = self._parse_form(form)
        self.bc = bc  # one of ``'finite', 'periodic', 'segment'``.

        # make copies of Bs and SVs
        self._B = [B.astype(dtype, copy=True) for B in Bs]
        self._S = [None] * (self.L + 1)
        for i in range(self.L + 1)[self.nontrivial_bonds]:
            self._S[i] = np.array(SVs[i], dtype=np.float)
        if self.bc == 'infinite':
            self._S[-1] = self._S[0]
        elif self.bc == 'finite':
            self._S[0] = self._S[-1] = np.ones([1])
        self.test_sanity()

    def test_sanity(self):
        """Sanity check. Raises Errors if something is wrong."""
        if self.bc not in self._valid_bc:
            raise ValueError("invalid boundary condition: " + repr(self.bc))
        if len(self._B) != self.L:
            raise ValueError("wrong len of self._B")
        if len(self._S) != self.L + 1:
            raise ValueError("wrong len of self._S")
        for i, B in enumerate(self._B):
            if not set(['vL', 'vR', 'p']) <= set(B.get_leg_labels()):
                raise ValueError("B has wrong labels " + repr(B.get_leg_labels()))
            B.test_sanity()  # recursive...
            if self._S[i].shape[-1] != B.get_leg('vL').ind_len or \
                    self._S[i+1].shape[0] != B.get_leg('vR').ind_len:
                raise ValueError("shape of B incompatible with len of singular values")
            if not self.finite or i + 1 < self.L:
                B2 = self._B[(i + 1) % self.L]
                B.get_leg('vR').test_contractible(B2.get_leg('vL'))
        if self.bc == 'finite':
            if len(self._S[0]) != 1 or len(self._S[-1]) != 1:
                raise ValueError("non-trivial outer bonds for finite MPS")
        elif self.bc == 'infinite':
            if np.any(self._S[self.L] != self._S[0]):
                raise ValueError("iMPS with S[0] != S[L]")
        assert len(self.form) == self.L
        for f in self.form:
            if f is not None:
                assert isinstance(f, tuple)
                assert len(f) == 2

    @classmethod
    def from_product_state(cls,
                           sites,
                           p_state,
                           bc='finite',
                           dtype=np.float,
                           form='B',
                           chargeL=None):
        """ Construct a matrix product state from a given product state.

        Parameters
        ----------
        sites : list of :class:`~tenpy.networks.site.Site`
            The sites defining the local Hilbert space.
        p_state : iterable of {int | 1D array}
            Defines the product state.
            If ``p_state[i]`` is int, then site ``i`` is in state ``p_state[i]``
            If ``p_state[i]`` is an array, then site ``i`` wavefunction is ``p_state[i]``
        bc : {'infinite', 'finite', 'segmemt'}
            MPS boundary conditions. See docstring of :class:`MPS`.
        dtype : type or string
            The data type of the array entries.
        form : (list of) {``'B' | 'A' | 'C' | 'G' | None`` | tuple(float, float)}
            Defines the canonical form. See module doc-string.
            A single choice holds for all of the entries.
        chargeL : charges
            Bond charges at bond 0, which are purely conventional.

        """
        sites = list(sites)
        L = len(sites)
        p_state = list(p_state)
        if len(p_state) != L:
            raise ValueError("Length of p_state does not match number of sites.")
        ci = sites[0].leg.chinfo
        Bs = []
        chargeL = ci.make_valid(chargeL)  # sets to zero if `None`
        legL = npc.LegCharge.from_qflat(ci, chargeL)

        for i, site in enumerate(sites):
            try:
                iter(p_state[i])
                if len(p_state[i]) != site.dim:
                    raise ValueError("p_state incompatible with local dim:" + repr(p_state[i]))
                B = np.array(p_state[i], dtype).reshape((site.dim, 1, 1))
            except TypeError:
                B = np.zeros((site.dim, 1, 1), dtype)
                B[p_state[i], 0, 0] = 1.0
            # calculate the LegCharge of the right leg
            legs = [site.leg, legL, None]  # other legs are known
            legs = npc.detect_legcharge(B, ci, legs, None, qconj=-1)
            B = npc.Array.from_ndarray(B, legs, dtype)
            B.set_leg_labels(['p', 'vL', 'vR'])
            Bs.append(B)
            legL = legs[-1].conj()  # prepare for next `i`
        if bc == 'infinite':
            # for an iMPS, the last leg has to match the first one.
            # so we need to gauge `qtotal` of the last `B` such that the right leg matches.
            chdiff = Bs[-1].get_leg('vR').charges[0] - Bs[0].get_leg('vL').charges[0]
            Bs[-1] = Bs[-1].gauge_total_charge('vR', ci.make_valid(chdiff))
        SVs = [[1.]] * (L + 1)
        return cls(sites, Bs, SVs, form=form, bc=bc)

    @classmethod
    def from_full(cls, sites, psi, form='B', cutoff=1.e-16):
        """Construct an MPS from a single tensor `psi` with one leg per physical site.

        Performs a sequence of SVDs of psi to split off the `B` matrices and obtain the singular
        values, the result will be in canonical form.
        Obviously, this is only well-defined for `finite` boundary conditions.

        Parameters
        ----------
        sites : list of :class:`~tenpy.networks.site.Site`
            The sites defining the local Hilbert space.
        psi : :class:`~tenpy.linalg.np_conserved.Array`
            The full wave function to be represented as an MPS.
            Should have labels ``'p0', 'p1', ...,  'p{L-1}'``.
        form  : ``'B' | 'A' | 'C' | 'G'``
            The canonical form of the resulting MPS, see module doc-string.
        cutoff : float
            Cutoff of singular values used in the SVDs.

        Returns
        -------
        psi_mps : :class:`MPS`
            MPS representation of `psi`, normalized and in canonical form.
        """
        if form not in ['B', 'A', 'C', 'G']:
            raise ValueError("Invalid form: " + repr(form))
        # perform SVDs to bring it into 'B' form, afterwards change the form.
        L = len(sites)
        assert (L >= 2)
        B_list = [None] * L
        S_list = [1] * (L + 1)
        labels = ['p' + str(i) for i in range(L)]
        psi.itranspose(labels)
        # combine legs from left
        psi = psi.add_trivial_leg(0, label='vL', qconj=+1)
        for i in range(0, L - 1):
            psi = psi.combine_legs([0, 1])  # combines the legs until `i`
        psi = psi.add_trivial_leg(2, label='vR', qconj=-1)
        # now psi has only three legs: ``'(((vL.p0).p1)...p{L-2})', 'p{L-1}', 'vR'``
        for i in range(L - 1, 0, -1):
            # split off B[i]
            psi = psi.combine_legs([labels[i], 'vR'])
            psi, S, B = npc.svd(psi, inner_labels=['vR', 'vL'], cutoff=cutoff)
            S /= np.linalg.norm(S)  # normalize
            psi.iscale_axis(S, 1)
            B_list[i] = B.split_legs(1).replace_label(labels[i], 'p')
            S_list[i] = S
            psi = psi.split_legs(0)
        psi = psi.combine_legs([labels[0], 'vR'])
        psi, S, B = npc.svd(psi,
                            qtotal_LR=[None, psi.qtotal],
                            inner_labels=['vR', 'vL'],
                            cutoff=cutoff)
        assert (psi.shape == (1, 1))
        S_list[0] = np.ones([1], dtype=np.float)
        B_list[0] = B.split_legs(1).replace_label(labels[0], 'p')
        res = cls(sites, B_list, S_list, bc='finite', form='B')
        if form != 'B':
            res.convert_form(form)
        return res

    @property
    def L(self):
        """Number of physical sites. For an iMPS the len of the MPS unit cell."""
        return len(self.sites)

    @property
    def dim(self):
        """List of local physical dimensions."""
        return [site.dim for site in self.sites]

    @property
    def finite(self):
        "Distinguish MPS (``True; bc='finite', 'segment'`` ) vs. iMPS (``False; bc='infinite'``)"
        assert (self.bc in self._valid_bc)
        return self.bc != 'infinite'

    @property
    def chi(self):
        """Dimensions of the (nontrivial) virtual bonds."""
        # s.shape[0] == len(s) for 1D numpy array, but works also for a 2D npc Array.
        return [s.shape[0] for s in self._S[self.nontrivial_bonds]]

    @property
    def nontrivial_bonds(self):
        """Slice of the non-trivial bond indices, depending on ``self.bc``."""
        if self.bc == 'finite':
            return slice(1, self.L)
        elif self.bc == 'segment':
            return slice(0, self.L + 1)
        elif self.bc == 'infinite':
            return slice(0, self.L)

    def get_B(self, i, form='B', copy=False, cutoff=1.e-16):
        """return (view of) `B` at site `i` in canonical form.

        Parameters
        ----------
        i : int
            Index choosing the site.
        form : ``'B' | 'A' | 'C' | 'G' | None`` | tuple(float, float)
            The (canonical) form of the returned B.
            For ``None``, return the matrix in whatever form it is.
        copy : bool
            Whether to return a copy even if `form` matches the current form.
        cutoff : float
            During DMRG with a mixer, `S` may be a matrix for which we need the inverse.
            This is calculated as the Penrose pseudo-inverse, which uses a cutoff for the
            singular values.

        Returns
        -------
        B : :class:`~tenpy.linalg.np_conserved.Array`
            The MPS 'matrix' `B` at site `i` with leg labels ``vL, vR, p`` (in undefined order).
            May be a view of the matrix (if ``copy=False``),
            or a copy (if the form changed or ``copy=True``)

        Raises
        ------
        ValueError : if self is not in canoncial form and ``form != None``.
        """
        i = self._to_valid_index(i)
        form = self._to_valid_form(form)
        return self._convert_form_i(self._B[i], i, self.form[i], form, copy, cutoff)

    def set_B(self, i, B, form='B'):
        """set `B` at site `i`.

        Parameters
        ----------
        i : int
            Index choosing the site.
        B : :class:`~tenpy.linalg.np_conserved.Array`
            The 'matrix' at site `i`. Should have leg labels ``vL, vR, p`` (in any order).
        form : ``'B' | 'A' | 'C' | 'G' | None`` | tuple(float, float)
            The (canonical) form of the `B` to set.
            ``None`` stands for non-canonical form.
        """
        i = self._to_valid_index(i)
        self.form[i] = self._to_valid_form(form)
        self._B[i] = B

    def get_SL(self, i):
        """return singular values on the left of site `i`"""
        i = self._to_valid_index(i)
        return self._S[i]

    def get_SR(self, i):
        """return singular values on the right of site `i`"""
        i = self._to_valid_index(i)
        return self._S[i + 1]

    def set_SL(self, i, S):
        """set singular values on the left of site `i`"""
        i = self._to_valid_index(i)
        self._S[i] = S
        if not self.finite and i == 0:
            self._S[self.L] = S

    def set_SR(self, i, S):
        """set singular values on the right of site `i`"""
        i = self._to_valid_index(i)
        self._S[i + 1] = S
        if not self.finite and i == self.L - 1:
            self._S[0] = S

    def get_theta(self, i, n=2, cutoff=1.e-16, formL=1., formR=1.):
        """Calculates the `n`-site wavefunction on ``sites[i:i+n]``.

        Parameters
        ----------
        i : int
            Site index.
        n : int
            Number of sites. The result lives on ``sites[i:i+n]``.
        cutoff : float
            During DMRG with a mixer, `S` may be a matrix for which we need the inverse.
            This is calculated as the Penrose pseudo-inverse, which uses a cutoff for the
            singular values.
        formL : float
            Exponent for the singular values to the left.
        formR : float
            Exponent for the singular values to the right.

        Returns
        -------
        theta : :class:`~tenpy.linalg.np_conserved.Array`
            The n-site wave function with leg labels ``vL, vR, p0, p1, .... p{n-1}``
            (in undefined order).
            In Vidal's notation (with s=lambda, G=Gamma):
            ``theta = s**form_L G_i s G_{i+1} s ... G_{i+n-1} s**form_R``.
        """
        i = self._to_valid_index(i)
        if self.finite:
            if (i < 0 or i + n > self.L):
                raise ValueError("i = {0:d} out of bounds".format(i))

        if self.form[i] is None or self.form[(i + n - 1) % self.L] is None:
            # we allow intermediate `form`=None except at the very left and right.
            raise ValueError("can't calculate theta for non-canonical form")

        # the following code is an equivalent to::
        #
        #   theta = self.get_B(i, form='B').replace_label('p', 'p0')
        #   theta.iscale_axis(self.get_SL(i)** formL, 'vL')
        #   for k in range(1, n):
        #       j = (i + n) % self.L
        #       B = self.get_B(j, form='B').replace_label('p', 'p'+str(k))
        #       theta = npc.tensordot(theta, B, ['vR', 'vL'])
        #   theta.iscale_axis(self.get_SR(i + n - 1)** (formR-1.), 'vR')
        #   return theta
        #
        # However, the following code is nummerically more stable if ``self.form`` is not `B`
        # (since it avoids unnecessary `scale_axis`) and works also for intermediate sites with
        # ``self.form[j] = None``.

        fL, fR = self.form[i]  # left / right form exponent
        copy = (fL == 0 and fR == 0)  # otherwise, a copy is performed later by `scale_axis`.
        theta = self.get_B(i, form=None, copy=copy)  # in the current form
        theta = theta.replace_label('p', 'p0')
        theta = self._scale_axis_B(theta, self.get_SL(i), formL - fL, 'vL', cutoff)
        for k in range(1, n):  # nothing if n=1.
            j = (i + k) % self.L
            B = self.get_B(j, None, False).replace_label('p', 'p' + str(k))
            if self.form[j] is not None:
                fL_j, fR_j = self.form[j]
                if fR is not None:
                    B = self._scale_axis_B(B, self.get_SL(j), 1. - fL_j - fR, 'vL', cutoff)
                # otherwise we can just hope it's fine.
                fR = fR_j
            else:
                fR = None
            theta = npc.tensordot(theta, B, axes=('vR', 'vL'))
        # here, fR = self.form[i+n-1][1]
        theta = self._scale_axis_B(theta, self.get_SR(i + n - 1), formR - fR, 'vR', cutoff)
        return theta

    def convert_form(self, new_form='B'):
        """tranform self into different canonical form (by scaling the legs with singular values).

        Parameters
        ----------
        new_form : (list of) {``'B' | 'A' | 'C' | 'G' | None`` | tuple(float, float)}
            The form the stored 'matrices'. The table in module doc-string.
            A single choice holds for all of the entries.

        Raises
        ------
        ValueError : if trying to convert from a ``None`` form. Use :meth:`canonicalize` instead!
        """
        new_forms = self._parse_form(new_form)
        for i, form in enumerate(new_forms):
            new_B = self.get_B(i, form=form, copy=False)  # calculates the desired form.
            self.set_B(i, new_B, form=form)

    def overlap(self, other):
        """Compute overlap :math:`<self | other>`.

        Parameters
        ----------
        other : :class:`MPS`
            An MPS of the same

        .. todo :
            implement
        """
        raise NotImplementedError("TODO")

    def expectation_value(self, ops, sites=None, axes=None):
        """Expectation value ``<psi|ops|psi>`` of (n-site) operator(s).

        Given the MPS in canonical form, it calculates n-site expectation values.
        For examples the contraction for a two-site (`n`=2) operator on site `i` would look like::

            |          .--S--B[i]--B[i+1]--.
            |          |     |     |       |
            |          |     |-----|       |
            |          |     | op  |       |
            |          |     |-----|       |
            |          |     |     |       |
            |          .--S--B*[i]-B*[i+1]-.

        Parameters
        ----------
        ops : (list of) { :class:`~tenpy.linalg.np_conserved.Array` | str }
            The operators, for wich the expectation value should be taken,
            All operators should all have the same number of legs (namely `2 n`).
            If less than ``len(sites)`` operators are given, we repeat them periodically.
            Strings (like ``'Id', 'Sz'``) are translated into single-site operators defined by the `self.sites`.
            with ``self.sites[i]
        sites : list
            List of site indices. ``sites``. Expectation values are evaluated there.
            If ``None`` (default), the entire chain is taken (clipping for finite b.c.)
        axes : None | (list of str, list of str)
            Two lists of each `n` leg labels giving the physical legs of the operator used for
            contaction. The first `n` legs are contracted with conjugated B`s,
            the second `n` legs with the non-conjugated `B`.
            ``None`` defaults to ``(['p'], ['p*'])`` for single site (`n` = 1), or
            ``(['p0', 'p1', ... 'p{n-1}'], ['p0*', 'p1*', .... 'p{n-1}*'])`` for `n` > 1.

        Returns
        -------
        exp_vals : 1D ndarray
            Expectation values, ``exp_vals[i] = <psi|ops[i]|psi>``, where ``ops[i]`` acts on
            site(s) ``j, j+1, ..., j+{n-1}`` with ``j=sites[i]``.

        Examples
        --------
        One site examples (`n` = 1):
        >>> psi.expectation_value('Sz')
        [Sz0, Sz1, ..., Sz{L-1}]
        >>> psi.expectation_value(['Sz', 'Sx'])
        [Sz0, Sx1, Sz2, Sx3, ... ]
        >>> psi.expectation_value('Sz', sites=[0, 3, 4])
        [Sz0, Sz3, Sz4]

        Two site example (`n` = 2):
        >>> SzSx = npc.outer(psi.sites[0].Sz.replace_labels(['p', 'p*'], ['p0', 'p0*']),
                             psi.sites[1].Sx.replace_labels(['p', 'p*'], ['p1', 'p1*']))
        >>> psi.expectation_value(SzSx)
        [Sz0Sx1, Sz1Sx2, Sz2Sx3, ... ]   # with len ``L-1`` for finite bc, or ``L`` for infinite
        """
        ops = to_iterable(ops)
        if isinstance(ops, npc.Array):  # an npc.Array is iterable...
            ops = [ops]  # ... so we need to do this manually
        if type(ops[0]) == str:
            n = 1
        else:
            n = ops[0].rank // 2  # same as int(ops[0].rank/2)
        L_ops = len(ops)
        L = self.L
        if sites is None:
            if self.finite:
                sites = range(L - (n - 1))
            else:
                sites = range(L)

        th_labels = ['vL', 'vR'] + ['p' + str(j) for j in range(n)]
        if axes is None:
            axes = (th_labels[2:], [lbl+'*' for lbl in th_labels[2:]])
        axes_p, axes_pstar = axes
        if len(axes_p) != n or len(axes_pstar) != n:
            raise ValueError("Len of axes does not match operator n=" + len(n))
        vLvR_axes_p = ('vL', 'vR') + tuple(axes_p)

        E = []
        for i in sites:
            op = ops[i % L_ops]
            if type(op) == str:
                op = self.sites[i].get_op(op)
            theta = self.get_theta(i, n)
            C = npc.tensordot(op, theta, axes=[axes_pstar, th_labels[2:]])
            E.append(npc.inner(theta, C, axes=[th_labels, vLvR_axes_p], do_conj=True))
        return np.array(E)

    def _to_valid_index(self, i):
        """make sure `i` is a valid index (depending on `self.bc`)."""
        if not self.finite:
            return i % self.L
        if i < 0:
            i += self.L
        if i >= self.L or i < 0:
            raise ValueError("i = {0:d} out of bounds for finite MPS".format(i))
        return i

    def _parse_form(self, form):
        """parse `form` = (list of) {tuple | key of _valid_forms} to list of tuples"""
        if isinstance(form, tuple):
            return [form] * self.L
        form = to_iterable(form)
        if len(form) == 1:
            form = [form[0]] * self.L
        if len(form) != self.L:
            raise ValueError("Wrong len of `form`: " + repr(form))
        return [self._to_valid_form(f) for f in form]

    def _to_valid_form(self, form):
        """parse `form` = {tuple | key of _valid_forms} to a tuple"""
        if isinstance(form, tuple):
            return form
        return self._valid_forms[form]

    def _convert_form_i(self, B, i, form, new_form, copy=True, cutoff=1.e-16):
        """transform `B[i]` from canonical form `form` into canonical form `new_form`.

        ======== ======== ================================================
        form     new_form action
        ======== ======== ================================================
        *        ``None`` return (copy of) B
        tuple    tuple    scale the legs 'vL' and 'vR' of B appropriately
                          with ``self.get_SL(i)`` and ``self.get_SR(i)``.
        ``None`` tuple    raise ValueError
        ======== ======== ================================================
        """
        if new_form is None or form == new_form:
            if copy:
                return B.copy()
            return B  # nothing to do
        if form is None:
            raise ValueError("can't convert form of non-canonical state!")
        old_L, old_R = form
        new_L, new_R = new_form
        B = self._scale_axis_B(B, self.get_SL(i), new_L - old_L, 'vL', cutoff)
        B = self._scale_axis_B(B, self.get_SR(i), new_R - old_R, 'vR', cutoff)
        return B

    def _scale_axis_B(self, B, S, form_diff, axis_B, cutoff):
        """Scale an axis of B with S to bring it in desired form.

        If S is just 1D (as usual, e.g. during TEBD), this function just performs
        ``B.scale_axis(S**form_diff, axis_B)``.

        However, during the DMRG with mixer, S might acutally be a 2D matrix.
        For ``form_diff = -1``, we need to calculate the inverse of S, more precisely the
        (Moore-Penrose) pseudo inverse, see :func:`~tenpy.linalg.np_conserved.pinv`.
        The cutoff is only used in that case.

        Returns scaled B."""
        if form_diff == 0:
            return B  # nothing to do
        if isinstance(S, npc.Array):
            if S.rank != 2:
                raise ValueError("Expect 2D npc.Array or 1D numpy ndarray")
            if form_diff == -1:
                S = npc.pinv(S, cutoff)
            elif form_diff != 1.:
                raise ValueError("Can't scale/tensordot a 2D `S` for non-integer `form_diff`")

            # Hack: mpo.MPOEnvironment.full_contraction uses ``axis_B == 'vL*'``
            if axis_B == 'vL' or axis_B == 'vL*':
                B = npc.tensordot(S, B, axes=[1, axis_B]).replace_label(0, axis_B)
            elif axis_B == 'vR' or axis_B == 'vR*':
                B = npc.tensordot(B, S, axes=[axis_B, 0]).replace_label(-1, axis_B)
            else:
                raise ValueError("This should never happen: unexpected leg for scaling with S")
            return B
        else:
            if form_diff != 1.:
                S = S**form_diff
            return B.scale_axis(S, axis_B)
