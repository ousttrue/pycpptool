// UNION FROM D2D

typedef float FLOAT;
typedef struct D2D_MATRIX_3X2_F
{
    union {
        struct
        {
            /// <summary>
            /// Horizontal scaling / cosine of rotation
            /// </summary>
            FLOAT m11;

            /// <summary>
            /// Vertical shear / sine of rotation
            /// </summary>
            FLOAT m12;

            /// <summary>
            /// Horizontal shear / negative sine of rotation
            /// </summary>
            FLOAT m21;

            /// <summary>
            /// Vertical scaling / cosine of rotation
            /// </summary>
            FLOAT m22;

            /// <summary>
            /// Horizontal shift (always orthogonal regardless of rotation)
            /// </summary>
            FLOAT dx;

            /// <summary>
            /// Vertical shift (always orthogonal regardless of rotation)
            /// </summary>
            FLOAT dy;
        };

        struct
        {
            FLOAT _11, _12;
            FLOAT _21, _22;
            FLOAT _31, _32;
        };

        FLOAT m[3][2];
    };

} D2D_MATRIX_3X2_F;
