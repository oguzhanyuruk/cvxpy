"""
Copyright 2017 Robin Verschueren

This file is part of CVXPY.

CVXPY is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

CVXPY is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with CVXPY.  If not, see <http://www.gnu.org/licenses/>.
"""

import numpy as np
import scipy.sparse as sp

from cvxpy.atoms import reshape
from cvxpy.constraints import SOC, ExpCone, NonPos, Zero
from cvxpy.solver_interface.reduction_solver import ReductionSolver


class ConicSolver(ReductionSolver):
    """Conic solver class with reduction semantics
    """

    @staticmethod
    def get_coeff_offset(expr):
        """Return the coefficient and offset in A*x + b.

        Args:
          expr: A CVXPY expression.

        Returns:
          (SciPy COO sparse matrix, NumPy 1D array)
        """
        # May be a reshape as root.
        if type(expr) == reshape:
            expr = expr.args[0]
        # Convert data to float64.
        offset = expr.args[1].value.ravel().astype(np.float64)
        coeff = expr.args[0].args[0].value.astype(np.float64)
        # Convert scalars to sparse matrices.
        if np.isscalar(coeff):
            coeff = sp.coo_matrix(([coeff], ([0], [0])), shape=(1, 1))
        return (coeff, offset)

    @staticmethod
    def get_spacing_matrix(shape, spacing, offset):
        """Returns a sparse matrix that spaces out an expression.

        Parameters
        ----------
        shape : tuple
            (rows in matrix, columns in matrix)
        spacing : int
            The number of rows between each non-zero.
        offset : int
            The number of zero rows at the beginning of the matrix.

        Returns
        -------
        SciPy CSR matrix
            A sparse matrix
        """
        val_arr = []
        row_arr = []
        col_arr = []
        # Selects from each column.
        for var_row in range(shape[1]):
            val_arr.append(np.float64(1.0))
            row_arr.append(spacing*var_row + offset)
            col_arr.append(var_row)
        return sp.coo_matrix((val_arr, (row_arr, col_arr)), shape).tocsr()

    @staticmethod
    def format_constr(constr, exp_cone_order):
        """Return the coefficient and offset for the constraint in ECOS format.

        Args:
          constr: A CVXPY constraint.

        Returns:
          (SciPy CSR sparse matrix, NumPy 1D array)
        """
        coeffs = []
        offsets = []
        for arg in constr.args:
            coeff, offset = ConicSolver.get_coeff_offset(arg)
            coeffs.append(coeff.tocsr())
            offsets.append(offset)
        height = sum([c.shape[0] for c in coeffs])
        # Specialize based on constraint type.
        if type(constr) in [NonPos, Zero]:
            return coeffs[0], -offsets[0]
        elif type(constr) == SOC:
            # Group each t row with appropriate X rows.
            mat_arr = []
            offset = np.zeros(height, dtype=np.float64)
            if constr.axis == 0:
                gap = constr.args[1].shape[0] + 1
            else:
                gap = constr.args[1].shape[1] + 1
            for i in range(constr.args[0].size):
                offset[i*gap] = offsets[0][i]
                mat_arr.append(coeffs[0][i, :])
                if constr.axis == 0:
                    offset[i*gap+1:(i+1)*gap] = offsets[1][i*(gap-1):(i+1)*(gap-1)]
                    mat_arr.append(coeffs[1][i*(gap-1):(i+1)*(gap-1), :])
                else:
                    offset[i*gap+1:(i+1)*gap] = offsets[1][i::gap-1]
                    mat_arr.append(coeffs[1][i::gap-1, :])
            return -sp.vstack(mat_arr), offset
        elif type(constr) == ExpCone:
            for i, coeff in enumerate(coeffs):
                mat = ConicSolver.get_spacing_matrix((height, coeff.shape[0]),
                                              len(exp_cone_order),
                                              exp_cone_order[i])
                offsets[i] = mat*offsets[i]
                coeffs[i] = -mat*coeffs[i]
            return sum(coeffs), sum(offsets)
        else:
            raise ValueError("Unsupported constraint type.")

    @staticmethod
    def group_coeff_offset(constraints, exp_cone_order):
        """Combine the constraints into a single matrix, offset.

        Args:
          constraints: A list of CVXPY constraints.

        Returns:
          (SciPy CSC sparse matrix, NumPy 1D array)
        """
        matrices = []
        offsets = []
        for cons in constraints:
            coeff, offset = ConicSolver.format_constr(cons, exp_cone_order)
            matrices.append(coeff)
            offsets.append(offset)
        if len(constraints) > 0:
            coeff = sp.vstack(matrices).tocsc()
            offset = np.hstack(offsets)
        else:
            coeff = None
            offset = None
        return coeff, offset

    @staticmethod
    def get_dual_values(result_vec, constraints):
        """Gets the values of the dual variables.

        Parameters
        ----------
        result_vec : array_like
            A vector containing the dual variable values.
        constraints : list
            A list of the constraints in the problem.

        Returns
        -------
           A map of constraint id to dual variable value.
        """
        # Store dual values.
        dual_vars = {}
        offset = 0
        for constr in constraints:
            # TODO reshape based on dual variable size.
            dual_vars[constr.id] = result_vec[offset:offset + constr.size]
            offset += constr.size
        return dual_vars
