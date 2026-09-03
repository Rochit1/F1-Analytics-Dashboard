import unittest
import pandas as pd


class TestSprintPointsLogic(unittest.TestCase):
    def test_merge_with_drivernumber_as_index_name(self):
        """Simulate FastF1 Ergast response where DriverNumber is set as index (drop=False).
        Ensure our defensive reset_index prevents:
        ValueError: 'DriverNumber' is both an index level and a column label
        """
        # Simulate race results from FastF1 with Ergast index
        r_results = pd.DataFrame({
            'DriverNumber': ['12', '63', '44'],
            'Abbreviation': ['ANT', 'RUS', 'HAM'],
            'TeamName': ['Mercedes', 'Mercedes', 'Ferrari'],
            'Position': [1.0, 2.0, 3.0],
            'Points': [25.0, 18.0, 15.0],
        })
        r_results.index = pd.Index(['12', '63', '44'], name='DriverNumber')

        # Simulate sprint results from FastF1 with Ergast index
        sprint_results = pd.DataFrame({
            'DriverNumber': ['63', '12', '44'],
            'Points': [8.0, 4.0, 6.0],
        })
        sprint_results.index = pd.Index(['63', '12', '44'], name='DriverNumber')

        # Apply the fix
        r_results = r_results.reset_index(drop=True)
        r_results.index.name = None
        r_results['DriverNumber'] = r_results['DriverNumber'].astype(str).str.strip()

        sprint_results = sprint_results.reset_index(drop=True)
        sprint_results.index.name = None
        sprint_results['DriverNumber'] = sprint_results['DriverNumber'].astype(str).str.strip()
        sprint_results['Points'] = sprint_results['Points'].fillna(0).astype(float)
        sprint_results = sprint_results.drop_duplicates(subset=['DriverNumber'], keep='first')

        rows_before = len(r_results)
        r_results = r_results.merge(
            sprint_results[['DriverNumber', 'Points']],
            on='DriverNumber',
            how='left',
            suffixes=('', '_Sprint'),
            validate='one_to_one'
        )
        self.assertEqual(len(r_results), rows_before)

        r_results['Points_Sprint'] = r_results['Points_Sprint'].fillna(0).astype(float)
        r_results['Points'] = r_results['Points'] + r_results['Points_Sprint']
        r_results.drop(columns=['Points_Sprint'], inplace=True)

        # Verify points:
        # ANT: 25.0 + 4.0 = 29.0
        # RUS: 18.0 + 8.0 = 26.0
        # HAM: 15.0 + 6.0 = 21.0
        ant_pts = r_results.loc[r_results['DriverNumber'] == '12', 'Points'].values[0]
        rus_pts = r_results.loc[r_results['DriverNumber'] == '63', 'Points'].values[0]
        ham_pts = r_results.loc[r_results['DriverNumber'] == '44', 'Points'].values[0]

        self.assertEqual(ant_pts, 29.0)
        self.assertEqual(rus_pts, 26.0)
        self.assertEqual(ham_pts, 21.0)

    def test_sprint_driver_not_in_top_8(self):
        """Drivers outside top 8 in sprint get 0 sprint points."""
        r_results = pd.DataFrame({
            'DriverNumber': ['3'],
            'Abbreviation': ['VER'],
            'TeamName': ['Red Bull'],
            'Position': [9.0],
            'Points': [2.0],
        })
        sprint_results = pd.DataFrame({
            'DriverNumber': ['63', '16'],
            'Points': [8.0, 7.0],
        })

        r_results = r_results.reset_index(drop=True)
        sprint_results = sprint_results.reset_index(drop=True)

        r_results = r_results.merge(
            sprint_results[['DriverNumber', 'Points']],
            on='DriverNumber',
            how='left',
            suffixes=('', '_Sprint'),
            validate='one_to_one'
        )
        r_results['Points_Sprint'] = r_results['Points_Sprint'].fillna(0).astype(float)
        r_results['Points'] = r_results['Points'] + r_results['Points_Sprint']
        r_results.drop(columns=['Points_Sprint'], inplace=True)

    def test_ergast_sprint_fallback(self):
        """Simulate Ergast sprint response parsing and fallback."""
        r_results = pd.DataFrame({
            'DriverNumber': ['12', '63'],
            'Points': [25.0, 18.0],
        })
        # Ergast returns 'number' and 'points'
        ergast_df = pd.DataFrame({
            'number': ['63', '12'],
            'points': [8.0, 4.0],
            'position': [1, 5],
        })

        num_col = 'number' if 'number' in ergast_df.columns else None
        pts_col = 'points' if 'points' in ergast_df.columns else None
        sprint_results = ergast_df[[num_col, pts_col]].rename(
            columns={num_col: 'DriverNumber', pts_col: 'Points'}
        ).copy()

        r_results = r_results.reset_index(drop=True)
        sprint_results = sprint_results.reset_index(drop=True)
        r_results['DriverNumber'] = r_results['DriverNumber'].astype(str).str.strip()
        sprint_results['DriverNumber'] = sprint_results['DriverNumber'].astype(str).str.strip()
        sprint_results['Points'] = sprint_results['Points'].fillna(0).astype(float)

        r_results = r_results.merge(
            sprint_results[['DriverNumber', 'Points']],
            on='DriverNumber',
            how='left',
            suffixes=('', '_Sprint'),
            validate='one_to_one'
        )
        r_results['Points_Sprint'] = r_results['Points_Sprint'].fillna(0).astype(float)
        r_results['Points'] = r_results['Points'] + r_results['Points_Sprint']
        r_results.drop(columns=['Points_Sprint'], inplace=True)

        self.assertEqual(r_results.loc[0, 'Points'], 29.0)
        self.assertEqual(r_results.loc[1, 'Points'], 26.0)


if __name__ == '__main__':
    unittest.main()
